# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "context",
  "path",
  "step",
]

def RunSteps(api):
  was_infra_failure = None
  try:
    api.step('boom', ['echo', 'hello'])
  except api.step.InfraFailure:  # pragma: no cover
    assert False, 'impossible'
  except api.step.StepFailure:
    was_infra_failure = False

  assert was_infra_failure is False

  with api.context(infra_steps=True):
    was_infra_failure = None
    try:
      api.step('boom 2', ['echo', 'hello', 'subdir'])
    except api.step.InfraFailure:
      was_infra_failure = True
    except api.step.StepFailure:  # pragma: no cover
      assert False, 'impossible'
    assert was_infra_failure is True

def GenTests(api):
  yield (
    api.test('basic')
    + api.step_data('boom', retcode=1)
    + api.step_data('boom 2', retcode=1)
  )

