# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass

from recipe_engine import post_process
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


@dataclass
class TEST_DEPS(RecipeTestApi):
  cv: cv.TEST_API


from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api: DEPS):
  api.step('no builds actually triggered', cmd=[])
  api.cv.record_triggered_builds(*[])
  assert api.cv.triggered_build_ids == []

  api.step('triggered some builds', cmd=[])
  api.cv.record_triggered_build_ids(1, 2)
  api.cv.record_triggered_builds(Build(id=22), Build(id=11))
  assert api.cv.triggered_build_ids == [1, 2, 22, 11]


def GenTests(api: TEST_DEPS):
  yield api.test(
      'example',
      api.cv.check_triggered_build_ids(1, 2, 22, 11),
  )

  yield api.test(
      'with_post_check',
      api.post_check(api.cv.check_triggered_build_ids, 1, 2, 22, 11),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with_post_process',
      api.post_process(api.cv.check_triggered_build_ids, 1, 2, 22, 11),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with_sequence',
      api.cv.check_triggered_build_ids([1, 2, 22, 11]),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'step_check',
      api.cv.check_triggered_build_ids(
          1, 2, 22, 11, step_name='triggered some builds'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'empty_step_check',
      api.cv.check_triggered_build_ids(
          step_name='no builds actually triggered'),
      api.post_process(post_process.DropExpectation),
  )
