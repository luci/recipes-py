# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    context,
    path,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  path: path.API
  step: step.API


def RunSteps(api: DEPS):
  api.step('no cwd', ['echo', 'hello'])

  with api.context(cwd=api.path.start_dir / 'subdir'):
    api.step('with cwd', ['echo', 'hello', 'subdir'])

  with api.context(cwd=None):
    api.step('with cwd=None', ['echo', 'hello', 'subdir'])


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
