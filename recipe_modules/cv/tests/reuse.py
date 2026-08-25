# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    cv,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  cv: cv.API
  step: step.API


def RunSteps(api: DEPS):
  api.step('disallow reuse only for full run', cmd=None)
  api.assertions.assertFalse(api.cv.allowed_reuse_modes)
  with api.assertions.assertRaises(ValueError):
    api.cv.allow_reuse_for()  # must provide at least one modes
  api.cv.allow_reuse_for(api.cv.QUICK_DRY_RUN)
  api.assertions.assertListEqual(api.cv.allowed_reuse_modes, [
      api.cv.QUICK_DRY_RUN,
  ])
  api.cv.allow_reuse_for(api.cv.DRY_RUN, api.cv.FULL_RUN)
  api.assertions.assertListEqual(api.cv.allowed_reuse_modes,
                                 [api.cv.DRY_RUN, api.cv.FULL_RUN])


def GenTests(api: RecipeTestApi):
  yield api.test('example')
