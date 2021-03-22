# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that output properties can be a proto message."""

from PB.recipes.recipe_engine.engine_tests.proto_output_properties import (
  Output, Msg)

DEPS = [
  'step',
]

def RunSteps(api):
  step_result = api.step('proto output properties', cmd=None)
  output = Output(
    str='foo',
    strs=['bar', 'baz'],
    msg = Msg(
      num=1,
      nums=[10, 11, 12],
    )
  )
  step_result.presentation.properties['$mod/proto_out'] = output

def GenTests(api):
  yield api.test('basic')
