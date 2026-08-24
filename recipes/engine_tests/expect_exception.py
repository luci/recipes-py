# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that tests with a single exception are handled correctly."""

from __future__ import annotations

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

def my_function(): # pragma: no cover
  raise TypeError("BAD DOGE")


def RunSteps(api: DEPS):
  my_function()


def GenTests(api: TEST_DEPS):
  yield (api.test('basic') + api.expect_exception('TypeError') +
         api.post_process(post_process.StatusException) +
         api.post_process(post_process.SummaryMarkdown,
                          "Uncaught Exception: TypeError('BAD DOGE')"))
