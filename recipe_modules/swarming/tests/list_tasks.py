# Copyright 2025 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    swarming,
    time,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  swarming: swarming.API
  time: time.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  time: time.TEST_API


def RunSteps(api: DEPS):
  tasks = api.swarming.list_tasks(
      'List Tasks', tags=['foo:bar'], start=api.time.time())
  api.assertions.assertEqual(len(tasks), 1)
  api.assertions.assertEqual(tasks[0]['tags'], ['foo:bar'])


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.time.seed(12341234),
      api.post_process(post_process.StepCommandContains, 'List Tasks',
                       ['-tag', 'foo:bar']),
      api.post_process(post_process.StepCommandContains, 'List Tasks',
                       ['-start', '12341235.5']),
      api.post_process(post_process.DropExpectation),
  )
