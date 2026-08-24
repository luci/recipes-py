# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that we can pass data via api.recipe_test_data."""

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

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
  target = 'production'
  if api._test_data.enabled:
    if 'target' in api._test_data:
      target = api._test_data['target']
  api.step('echo', ['echo', target])


def GenTests(api: TEST_DEPS):
  yield api.test(
      'default',
      api.post_check(
          lambda check, steps: check([..., 'production'] in steps['echo'].cmd)
      ),
      api.post_process(DropExpectation),
  )
  yield api.test(
      'override',
      api.recipe_test_data(target='override'),
      api.post_check(
          lambda check, steps: check([..., 'override'] in steps['echo'].cmd)
      ),
      api.post_process(DropExpectation),
  )
