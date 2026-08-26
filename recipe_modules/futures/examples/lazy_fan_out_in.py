# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    futures,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  futures: futures.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  futures = []
  for i in range(10):
    def _runner(i):
      api.step(
          'sleep loop [%d]' % (i+1),
          ['python3', '-u', api.resource('sleep_loop.py'), i],
          cost=api.step.ResourceCost(),
      )
      return i + 1
    futures.append(api.futures.spawn(_runner, i))

  for helper in api.futures.iwait(futures):
    api.step('Sleeper %d complete' % helper.result(), cmd=None)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
