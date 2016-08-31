# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Launches the repo bundler."""

DEPS = [
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


def GenTests(api):
  yield api.test('basic')
