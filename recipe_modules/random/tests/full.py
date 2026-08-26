# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    random,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  random: random.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  random: random.TEST_API


def RunSteps(api: DEPS):
  my_list = list(range(10))
  api.random.shuffle(my_list)
  api.step('echo list', ['echo', ', '.join(map(str, my_list))])

  my_randrange = [api.random.randrange(1000, 15000000, 3) for _ in range(10)]
  api.step('echo randrange', ['foo'] + list(map(str, my_randrange)))


def GenTests(api: TEST_DEPS):
  yield api.test("basic")

  yield api.test("reseed") + api.random.seed(4321)
