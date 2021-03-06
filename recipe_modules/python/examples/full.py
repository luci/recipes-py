# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Launches the repo bundler."""

DEPS = [
  'path',
  'python',
  'raw_io',
  'step',
]


def RunSteps(api):
  api.python.succeeding_step("success", ["This step is a success"],
                             as_log='success')

  # Test that a failing step raises StepFailure.
  was_failure = False
  try:
    api.python.failing_step("failure", "This step is a failure :(")
  except api.step.StepFailure:
    was_failure = True
  assert was_failure

  # Test that unbufferred actually removes PYTHONUNBUFFERED envvar.
  api.python('run json.tool', '-m', [
    'json.tool', api.raw_io.input('{"something":[true,true]}'),
  ], unbuffered=False)

  api.python.inline('inline', 'print "Hello World!"')

  # Test "vpython"-based invocation.
  #
  # The "test.py" script has an inline VirtualEnv spec that is read by default
  # when "vpython" is invoked.
  #
  # The second invocation uses an explicit spec with a different package set to
  # verify that the explicit spec is loaded instead of the inline spec.
  api.python('run vpython.inlinespec', api.resource('test.py'),
             args=['--verify-enum34'], venv=True)
  api.python('run vpython.spec', api.resource('test.py'),
             args=['--verify-six'], venv=api.resource('test.vpython'))


def GenTests(api):
  yield api.test('basic')
