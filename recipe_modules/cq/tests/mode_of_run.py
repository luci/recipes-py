# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    cq,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  cq: cq.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  cq: cq.TEST_API
  properties: properties.TEST_API


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api: DEPS):
  api.step('show properties', [])
  api.step.active_result.presentation.logs['result'] = [
    'mode: %s' % (api.cq.run_mode,),
  ]


def GenTests(api: TEST_DEPS):
  yield api.test('dry') + api.cq(run_mode=api.cq.DRY_RUN)
  yield api.test('quick-dry') + api.cq(run_mode=api.cq.QUICK_DRY_RUN)
  yield api.test('full') + api.cq(run_mode=api.cq.FULL_RUN)
  yield api.test('legacy-full') + api.properties(**{
    '$recipe_engine/cq': {'dry_run': False},
  })
  yield api.test('legacy-dry') + api.properties(**{
    '$recipe_engine/cq': {'dry_run': True},
  })
