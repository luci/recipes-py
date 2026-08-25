# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    cv,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  cv: cv.API
  step: step.API


from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api: DEPS):
  assert not api.cv.do_not_retry_build
  api.cv.set_do_not_retry_build()
  assert api.cv.do_not_retry_build
  api.cv.set_do_not_retry_build()  # noop.


def GenTests(api: RecipeTestApi):
  yield api.test('example')
