# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
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


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api: DEPS):
  api.step('no builds actually triggered', cmd=[])
  api.cq.record_triggered_builds(*[])
  assert api.cq.triggered_build_ids == []

  api.step('triggered some builds', cmd=[])
  api.cq.record_triggered_build_ids(1, 2)
  api.cq.record_triggered_builds(Build(id=22), Build(id=11))
  assert api.cq.triggered_build_ids == [1, 2, 22, 11]


def GenTests(api: RecipeTestApi):
  yield api.test('example')
