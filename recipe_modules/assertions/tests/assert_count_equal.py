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
from RECIPE_MODULES.recipe_engine import assertions


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API


def RunSteps(api: DEPS) -> None:
  api.assertions.assertCountEqual([0, 1], (1, 0))


def GenTests(api: RecipeTestApi) -> Iterator[recipe_test_api.TestData]:
  yield api.test(
      'basic',
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
