# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step presentation properties can be ordered."""

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'step',
]

def RunSteps(api):
  step_result = api.step('property_step', cmd=None)
  for k, v in [('a', 'a'), ('d', 'd'), ('b', 'b'), ('c', 'c')]:
    step_result.presentation.properties[k] = v

def GenTests(api):
  yield api.test('basic')
