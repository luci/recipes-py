# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

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


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
