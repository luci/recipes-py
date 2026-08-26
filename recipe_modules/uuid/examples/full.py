# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    step,
    uuid,
)


@dataclass
class DEPS(RecipeScriptApi):
  step: step.API
  uuid: uuid.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  api.step('echo', ['echo', api.uuid.random()])


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
