# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Iterator
from recipe_engine import recipe_test_api

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    cv,
    properties,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  cv: cv.API
  properties: properties.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


def RunSteps(api: DEPS) -> None:
  api.assertions.assertFalse(api.cv.active)


def GenTests(api: TEST_DEPS) -> Iterator[recipe_test_api.TestData]:
  yield (api.test('no cq properties') +
         api.post_process(post_process.DropExpectation))
  yield (api.test('empty cq properties') +
         api.properties(**{'$recipe_engine/cq': {}}) +
         api.post_process(post_process.DropExpectation))
