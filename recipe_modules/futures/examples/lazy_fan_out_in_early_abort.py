# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Iterator
from recipe_engine import recipe_test_api

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


def RunSteps(api: DEPS) -> None:
  futures = []
  for i in range(10):

    def _runner(i: int) -> int:
      api.step(
          'sleep loop [%d]' % (i+1),
          ['python3', '-u', api.resource('sleep_loop.py'), i],
      )
      return i + 1
    futures.append(api.futures.spawn(_runner, i))

  with api.futures.iwait(futures) as iter:
    for helper in iter:
      result = helper.result()
      if result < 5:
        api.step('Sleeper %d complete' % helper.result(), cmd=None)
      else:
        result = api.step('OH NO QUIT QUIT QUIT', cmd=None)
        result.presentation.status = 'FAILURE'
        raise api.step.StepFailure('boomzors')


def GenTests(api: TEST_DEPS) -> Iterator[recipe_test_api.TestData]:
  yield api.test('basic', status='FAILURE')
