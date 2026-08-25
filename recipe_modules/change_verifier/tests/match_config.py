# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    change_verifier,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  change_verifier: change_verifier.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API


def RunSteps(api: DEPS):
  group = api.change_verifier.match_config(
      'chromium-review.googlesource.com',
      123456)

  if group:
    api.step.empty('group found')
    api.step.empty(group)

  else:
    api.step.empty('group not found')


def GenTests(api: TEST_DEPS):
  yield api.test(
      'pass',
      api.buildbucket.ci_build(),
      api.post_process(post_process.MustRun, 'group found'),
      api.post_process(post_process.MustRun, 'chromium-src'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-found',
      api.buildbucket.ci_build(),
      api.step_data('match-config', retcode=1),
      api.post_process(post_process.MustRun, 'group not found'),
      api.post_process(post_process.DropExpectation),
  )
