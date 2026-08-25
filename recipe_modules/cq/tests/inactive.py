# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process, recipe_api

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    cq,
    properties,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  cq: cq.API
  properties: properties.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api: DEPS):
  api.assertions.assertFalse(api.cq.active)


def GenTests(api: TEST_DEPS):
  yield (
    api.test('no cq properties')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('empty cq properties')
    + api.properties(**{'$recipe_engine/cq': {}})
    + api.post_process(post_process.DropExpectation)
  )
