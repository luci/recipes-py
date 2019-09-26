# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'step',
]


def RunSteps(api):
  api.step('test step', [])
  api.step.active_result.presentation.logs['test_log'] = ['line 1', 'line2']
  api.step.active_result.presentation.step_text = 'test step text'

  # can explicitly close the active step
  api.step.close_non_nest_step()
  try:
    api.step.active_result
    assert False, "active_result didn't an exception?" # pragma: no cover
  except ValueError:
    pass


def GenTests(api):
  yield api.test('basic')
