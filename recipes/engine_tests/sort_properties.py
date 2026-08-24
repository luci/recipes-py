# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step presentation properties can be ordered."""

from __future__ import annotations

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
  step_result = api.step('property_step', cmd=None)
  for k, v in [('a', 'a'), ('d', 'd'), ('b', 'b'), ('c', 'c')]:
    step_result.presentation.properties[k] = v


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
