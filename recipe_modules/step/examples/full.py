# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.step.examples import full as full_pb
from recipe_engine import post_process

DEPS = [
    'buildbucket',
    'context',
    'json',
    'path',
    'properties',
    'step',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  bool access_invalid_data = 1;
  bool access_deep_invalid_data = 2;
  bool assign_extra_junk = 3;
  int32 timeout = 4;
}
"""

PROPERTIES = full_pb.InputProperties


def RunSteps(api, props: full_pb.InputProperties):
  if props.timeout:
    # Timeout causes the recipe engine to raise an exception if your step takes
    # longer to run than you allow. Units are seconds.
    if props.timeout == 1:
      api.step('timeout', ['sleep', '20'], timeout=1)
    elif props.timeout == 2:
      try:
        api.step('caught timeout', ['sleep', '20'], timeout=1)
      except api.step.StepFailure:
        return

  # TODO(martiniss) change this
  # The api.step object is directly callable.
  api.step('hello', ['echo', 'Hello World'])
  api.step('hello', ['echo', 'Why hello, there.'])

  # You can change the current working directory as well.
  api.step('mk subdir', ['mkdir', '-p', 'something'])
  with api.context(cwd=api.path.start_dir / 'something'):
    api.step('something', ['bash', '-c', 'echo Why hello, there, in a subdir.'])

  # By default, all steps run in 'start_dir', or the cwd of the recipe engine
  # when the recipe begins. Because of this, setting cwd to start_dir doesn't
  # show anything in particular in the expectations.
  with api.context(cwd=api.path.start_dir):
    api.step('start_dir ignored', ['bash', '-c', 'echo what happen'])

  # You can also manipulate various aspects of the step, such as env.
  # These are passed straight through to subprocess.Popen.
  # Also, abusing bash -c in this way is a TERRIBLE IDEA DON'T DO IT.
  with api.context(env={'friend': 'Darth Vader'}):
    api.step('goodbye', ['bash', '-c', 'echo Good bye, $friend.'])

  # You can modify the environment in terms of old environment. Environment
  # variables are substituted in for expressions of the form %(VARNAME)s.
  with api.context(env={'PATH': api.path.pathsep.join(
      [str(api.step.repo_resource()), '%(PATH)s'])}):
    api.step('recipes help', ['recipes.py', '--help'])

  # Finally, you can make your step accept any return code.
  api.step('anything is cool', ['bash', '-c', 'exit 3'],
           ok_ret='any')

  # We can manipulate the step presentation arbitrarily until we run
  # the next step.
  step_result = api.step('hello again', ['echo', 'hello'])
  step_result.presentation.status = api.step.EXCEPTION
  step_result.presentation.logs['the reason'] = ['The reason\nit failed']
  step_result.presentation.tags[u'hello.step_classification'] = u'PRINT_MESSAGE'

  # Without a command, a step can be used to present some data from the recipe.
  step_result = api.step('Just print stuff', cmd=None)
  step_result.presentation.logs['more'] = ['More stuff']

  # If you shove `bytes` in, you'll also get the non-UTF-8 encoded with
  # backslashreplace.
  step_result.presentation.logs['raw'] = bytes(b'\x1b[31mI am red!')
  step_result.presentation.logs['raw_lines'] = [
    bytes(b'\x1b[31mI am red!'),
    bytes(b'\x1b[32mI am green!'),
    bytes(b'\x1b[0mReset.'),
    bytes(b'I am normal'),
  ]

  # Some downstream recipes use `logs` in this way.
  # Please do not do this :(
  step_result.presentation.logs.setdefault('weird', []).append('stuff')
  step_result.presentation.logs['weird'] += [bytes(b'\x1b[31mmore'), 'lines']
  step_result.presentation.logs['weird'] = (
    step_result.presentation.logs['weird'] + ['strange'])
  step_result.presentation.logs['weird'][0] = bytes(b'\x1b[31mmore')

  try:
    api.step('goodbye', ['echo', 'goodbye'])
    # Modifying step_result now would raise an AssertionError.
  except api.step.StepFailure:
    # Raising anything besides StepFailure or StepWarning causes the build to go
    # purple.
    raise ValueError('goodbye must exit 0!')

  try:
    api.step('warning', ['echo', 'warning'])
  except api.step.StepFailure as e:
    e.result.presentation.status = api.step.WARNING
    raise api.step.StepWarning(str(e))

  # Some steps are needed from an infrastructure point of view. If these
  # steps fail, the build stops, but doesn't get turned red because it's
  # not the developers' fault.
  try:
    api.step('cleanup', ['echo', 'cleaning', 'up', 'build'], infra_step=True)
  except api.step.InfraFailure as f:
    assert f.result.presentation.status == api.step.EXCEPTION

  # Run a step through a made-up wrapper program.
  api.step('application', ['echo', 'main', 'application'],
           wrapper=['python3', '-c', 'import sys; print(sys.argv)'])

  if props.access_invalid_data:
    result = api.step('no-op', ['echo', 'I', 'do', 'nothing'])
    # Trying to access non-existent attributes on the result should raise.
    _ = result.json.output

  if props.access_deep_invalid_data:
    result = api.step('no-op', ['echo', api.json.output()])
    # Trying to access deep, non-existent attributes on the result should raise.
    _ = result.json.outpurt

  if props.assign_extra_junk:
    result = api.step('no-op', ['echo', 'I', 'do', 'nothing'])
    # Assigning extra junk to the result raises ValueError.
    result.json = "hi"


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('anything is cool', retcode=3),
  )

  # If you don't have the expect_exception in this test, you will get something
  # like this output.
  # ======================================================================
  # ERROR: step:example.exceptional (..../exceptional.json)
  # ----------------------------------------------------------------------
  # Traceback (most recent call last):
  #   <full stack trace omitted>
  #   File "annotated_run.py", line 537, in run
  #     retcode = steps_function(api)
  #   File "recipe_modules/step/examples/full.py", line 39, in RunSteps
  #     raise ValueError('goodbye must exit 0!')
  # ValueError: goodbye must exit 0!

  yield api.test(
      'exceptional',
      api.step_data('goodbye (2)', retcode=1),
      api.expect_exception('ValueError'),
      api.post_process(
          post_process.SummaryMarkdownRE,
          "goodbye must exit 0!"),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'warning',
      api.step_data('warning', retcode=1),
      status='FAILURE',
  )

  yield api.test(
      'invalid_access',
      api.properties(full_pb.InputProperties(access_invalid_data=True)),
      api.expect_exception('AttributeError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdownRE,
          "StepData from step 'no-op' has no attribute 'json'"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'deep_invalid_access',
      api.properties(full_pb.InputProperties(access_deep_invalid_data=True)),
      api.expect_exception('AttributeError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdownRE,
          r"StepData\('no-op'\)\.json has no attribute 'outpurt'"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'extra_junk',
      api.properties(full_pb.InputProperties(assign_extra_junk=True)),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdownRE,
          "Cannot assign to 'json' on finalized StepData from step 'no-op'"),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'infra_failure',
      api.step_data('cleanup', retcode=1),
  )

  yield api.test(
      'timeout',
      api.properties(full_pb.InputProperties(timeout=1)),
      api.step_data('timeout', times_out_after=20),
      status='FAILURE',
  )

  yield api.test(
      'catch_timeout',
      api.properties(full_pb.InputProperties(timeout=2)),
      api.step_data('caught timeout', times_out_after=20),
  )

  yield api.test(
      'tagged-steps',
      api.post_check(lambda check, steps: check(
          steps['hello again']
          .tags[u'hello.step_classification'] == u'PRINT_MESSAGE'
      )),
  )
