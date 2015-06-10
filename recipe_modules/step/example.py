# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'properties',
  'step',
]

from recipe_engine import recipe_api

def GenSteps(api):
  # TODO(martinis) change this
  # The api.step object is directly callable.
  api.step('hello', ['echo', 'Hello World'])
  api.step('hello', ['echo', 'Why hello, there.'])

  # You can also manipulate various aspects of the step, such as env.
  # These are passed straight through to subprocess.Popen.
  # Also, abusing bash -c in this way is a TERRIBLE IDEA DON'T DO IT.
  api.step('goodbye', ['bash', '-c', 'echo Good bye, $friend.'],
           env={'friend': 'Darth Vader'})

  # Finally, you can make your step accept any return code
  api.step('anything is cool', ['bash', '-c', 'exit 3'],
           ok_ret='any')

  # We can manipulate the step presentation arbitrarily until we run
  # the next step.
  step_result = api.step('hello', ['echo', 'hello'])
  step_result.presentation.status = api.step.EXCEPTION

  try:
    api.step('goodbye', ['echo', 'goodbye'])
    # Modifying step_result now would raise an AssertionError.
  except api.step.StepFailure:
    # Raising anything besides StepFailure causes the build to go purple.
    raise ValueError('goodbye must exit 0!')

  # Aggregate failures from tests!
  try:
    with recipe_api.defer_results():
      api.step('testa', ['echo', 'testa'])
      api.step('testb', ['echo', 'testb'])
  except recipe_api.AggregatedStepFailure as f:
    raise api.step.StepFailure("You can catch step failures.")

  # Some steps are needed from an infrastructure point of view. If these
  # steps fail, the build stops, but doesn't get turned red because it's
  # not the developers' fault.
  try:
    api.step('cleanup', ['echo', 'cleaning', 'up', 'build'], infra_step=True)
  except api.step.InfraFailure as f:
    assert f.result.presentation.status == api.step.EXCEPTION

  # Run a step through a made-up wrapper program.
  api.step('application', ['echo', 'main', 'application'],
           wrapper=['python', 'test-wrapper.py', '-v', '--'])

  if api.properties.get('access_invalid_data'):
    result = api.step('no-op', ['echo', 'I', 'do', 'nothing'])
    # Trying to access non-existent attributes on the result should raise.
    _ = result.json.output

  # You can also raise a warning, which will act like a step failure, but
  # will turn the build yellow, and stop the build.
  raise api.step.StepWarning("Warning, robots approaching!")


def GenTests(api):
  yield (
      api.test('basic') +
      api.step_data('anything is cool', retcode=3)
    )

  # If you don't have the expect_exception in this test, you will get something
  # like this output.
  # ======================================================================
  # ERROR: step:example.exceptional (..../exceptional.json)
  # ----------------------------------------------------------------------
  # Traceback (most recent call last):
  #   <full stack trace ommitted>
  #   File "annotated_run.py", line 537, in run
  #     retcode = steps_function(api)
  #   File "recipe_modules/step/example.py", line 39, in GenSteps
  #     raise ValueError('goodbye must exit 0!')
  # ValueError: goodbye must exit 0!

  yield (
      api.test('exceptional') +
      api.step_data('goodbye (2)', retcode=1) +
      api.expect_exception('ValueError')
    )

  yield (
      api.test('defer_results') +
      api.step_data('testa', retcode=1)
    )

  yield (
      api.test('invalid_access') +
      api.properties(access_invalid_data=True) +
      api.expect_exception('StepDataAttributeError')
    )

  yield (
      api.test('infra_failure') +
      api.properties(raise_infra_failure=True) +
      api.step_data('cleanup', retcode=1)
    )
