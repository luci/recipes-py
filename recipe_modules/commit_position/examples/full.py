# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    commit_position,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  commit_position: commit_position.API
  step: step.API


def RunSteps(api: DEPS):
  expected = ('refs/heads/main', 12345)
  actual = api.commit_position.parse('refs/heads/main@{#12345}')
  assert actual == expected, (actual, expected)

  try:
    api.commit_position.parse('main@{#12345}')
  except ValueError as ex:
    step_res = api.step('invalid', cmd=None)
    step_res.presentation.logs['ex'] = str(ex).splitlines()

  expected = 'refs/heads/main@{#12345}'
  actual = api.commit_position.format('refs/heads/main', 12345)
  assert actual == expected, (actual, expected)


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
