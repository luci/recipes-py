# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that tests with a single exception are handled correctly."""

from __future__ import annotations

from collections.abc import Iterator
from recipe_engine import recipe_test_api

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi


@dataclass
class DEPS(RecipeScriptApi):
  pass


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass

def my_function() -> None:  # pragma: no cover
  raise TypeError("BAD DOGE")


def RunSteps(api: DEPS) -> None:
  my_function()


def GenTests(api: TEST_DEPS) -> Iterator[recipe_test_api.TestData]:
  yield (api.test('basic') + api.expect_exception('TypeError') +
         api.post_process(post_process.StatusException) +
         api.post_process(post_process.SummaryMarkdown,
                          "Uncaught Exception: TypeError('BAD DOGE')"))
