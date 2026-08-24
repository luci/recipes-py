# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that output properties can be a proto message."""

from __future__ import annotations

from PB.recipes.recipe_engine.engine_tests.proto_output_properties import (
  Output, Msg)

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import step


@dataclass
class DEPS(RecipeScriptApi):
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
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


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
