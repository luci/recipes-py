# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


"""This test serves to demonstrate that the ModuleInjectionSite object on
recipe modules (i.e. the `.m`) also contains a reference to the module which
owns it.

This was implemented to aid in refactoring some recipes (crbug.com/782142).
"""

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    path,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  path: path.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  api.step("echo useless thing", ["echo", api.path.m.path.join("a", "b")])


def GenTests(api: TEST_DEPS):
  yield api.test("basic")
