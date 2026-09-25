# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This is a fake recipe to trick the simulation and make it believes that
this module has tests. The actual test for this module is done via unit test
because the `issue` method can only be used from recipe_modules, not recipes.
"""

from __future__ import annotations

from collections.abc import Iterator
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

from recipe_engine import post_process

def RunSteps(api: recipe_api.RecipeScriptApi) -> None:
  del api


def GenTests(
    api: recipe_test_api.RecipeTestApi,
) -> Iterator[recipe_test_api.TestData]:
  yield api.test('basic') + api.post_process(post_process.DropExpectation)
