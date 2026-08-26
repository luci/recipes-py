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


def worker(api, sem, i, N):
  with api.step.nest('worker %d' % i):
    with sem:
      api.step('serialized work', ['python3', api.resource('sleep.py'), 5])
    api.step('parallel work', ['python3', api.resource('sleep.py'), 5*N])


def RunSteps(api: DEPS):
  futures = []
  sem = api.futures.make_bounded_semaphore()
  # total time should be (5s * N) * 2
  N = 10
  for i in range(N):
    futures.append(api.futures.spawn(worker, api, sem, i, N, __meta=i))

  for fut in api.futures.iwait(futures):
    api.step('Sleeper %d complete' % fut.meta, cmd=None)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
