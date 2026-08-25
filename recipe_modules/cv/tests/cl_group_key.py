# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    cv,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  cv: cv.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  cv: cv.TEST_API

from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api: DEPS):
  assert api.cv.cl_group_key == 'changes-on-trivial-rebase', api.cv.cl_group_key
  assert api.cv.equivalent_cl_group_key == 'sticky-on-trivial-rebase', (
      api.cv.equivalent_cl_group_key)


def GenTests(api: TEST_DEPS):
  yield api.test(
      'simple',
      api.cv(run_mode=api.cv.DRY_RUN),
      api.buildbucket.try_build(
          change_number=123,
          tags=api.buildbucket.tags(
              cq_cl_group_key='changes-on-trivial-rebase',
              cq_equivalent_cl_group_key='sticky-on-trivial-rebase'),
      ),
      api.post_process(post_process.DropExpectation),
  )
