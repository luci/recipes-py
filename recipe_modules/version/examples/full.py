# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import version


@dataclass
class DEPS(RecipeScriptApi):
  version: version.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  assert api.version.parse('1.0.0') > api.version.parse('0.9')


def GenTests(api: TEST_DEPS):
  yield api.test('basic') + api.post_process(lambda *a: {})
