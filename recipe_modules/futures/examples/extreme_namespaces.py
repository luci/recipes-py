# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    context,
    futures,
    path,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  futures: futures.API
  path: path.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def Level2(api, i):
  work = []
  with api.step.nest('Level2 [%d]' % i):
    with api.context(cwd=api.path.start_dir / 'deep'):
      work.append(api.futures.spawn(
          api.step, 'cool step', cmd=['echo', 'cool']))

  # Specifically wait outside all the contexts; if they have a bug w.r.t. global
  # state vs. greenlet-local state, we'll see it here with bad context.
  api.futures.wait(work)


def Level1(api, i):
  with api.step.nest('Level1 [%d]' % i):
    for j in range(4):
      api.futures.spawn(Level2, api, j)


def RunSteps(api: DEPS):
  for i in range(4):
    api.futures.spawn(Level1, api, i)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
