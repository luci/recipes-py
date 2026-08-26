# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import resultdb


@dataclass
class DEPS(RecipeScriptApi):
  resultdb: resultdb.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  api.resultdb.config_test_presentation()


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
