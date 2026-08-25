# Copyright 2019 The LUCI Authors
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
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  cq: cq.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  cq: cq.TEST_API
  properties: properties.TEST_API


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api: DEPS):
  if 'raises' in api.properties:
    with api.assertions.assertRaises(api.cq.CQInactive):
      api.cq.experimental
    with api.assertions.assertRaises(api.cq.CQInactive):
      api.cq.top_level
    return

  api.assertions.assertEqual(
      api.cq.experimental, 'expected_experimental' in api.properties)
  api.assertions.assertEqual(
      api.cq.top_level, 'expected_top_level' in api.properties)


def GenTests(api: TEST_DEPS):
  yield (
    api.test('default')
    + api.cq(run_mode=api.cq.FULL_RUN)
    + api.properties(expected_top_level=True)
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('indirect and experimental')
    + api.cq(run_mode=api.cq.FULL_RUN, top_level=False, experimental=True)
    + api.properties(expected_experimental=True)
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('not a CQ run')
    + api.properties(raises=True)
    + api.post_process(post_process.DropExpectation)
  )
