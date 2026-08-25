# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    cq,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  cq: cq.API
  step: step.API


from PB.go.chromium.org.luci.buildbucket.proto.build import Build


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api: DEPS):
  assert not api.cq.do_not_retry_build
  api.cq.set_do_not_retry_build()
  assert api.cq.do_not_retry_build
  api.cq.set_do_not_retry_build()  # noop.


def GenTests(api: RecipeTestApi):
  yield api.test('example')
