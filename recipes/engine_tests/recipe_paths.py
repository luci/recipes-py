# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that recipes have access to names, resources and their repo."""

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
  api.step('some_resource', ['python3', api.resource('hello.py')])
  api.step('repo_root', ['echo', api.repo_resource('file', 'path')])


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
