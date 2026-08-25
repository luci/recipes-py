# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    cq,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  cq: cq.API
  step: step.API


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api: DEPS):
  api.step('disallow reuse only for full run', cmd=None)
  api.assertions.assertFalse(api.cq.allowed_reuse_modes)
  with api.assertions.assertRaises(ValueError):
    api.cq.allow_reuse_for()  # must provide at least one modes
  api.cq.allow_reuse_for(api.cq.QUICK_DRY_RUN)
  api.assertions.assertListEqual(api.cq.allowed_reuse_modes,
                                 [api.cq.QUICK_DRY_RUN,])
  api.cq.allow_reuse_for(api.cq.DRY_RUN, api.cq.FULL_RUN)
  api.assertions.assertListEqual(api.cq.allowed_reuse_modes,
                                 [api.cq.DRY_RUN, api.cq.FULL_RUN])


def GenTests(api: RecipeTestApi):
  yield api.test('example')
