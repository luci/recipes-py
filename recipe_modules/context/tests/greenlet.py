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
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  futures: futures.API
  step: step.API


def RunSteps(api: DEPS):
  # We want to make sure that context is kept per-greenlet.

  chan = api.futures.make_channel()
  with api.context(infra_steps=True):
    assert api.context.infra_step

    def _assert_still_true():
      chan.get()  # wait until we're totally out of the context
      assert api.context.infra_step

    future = api.futures.spawn(_assert_still_true)

  chan.put(None)
  future.result()

  api.step('we made it', ['echo', 'woot'])


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
