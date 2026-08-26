# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating reading/mocking scheduler host."""

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    scheduler,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  scheduler: scheduler.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  scheduler: scheduler.TEST_API


def RunSteps(api: DEPS):
  step_res = api.step(name='host', cmd=None)
  step_res.presentation.logs['info'] = [
      api.scheduler.host,
      '%s' % api.scheduler.job_id,
      '%s' % api.scheduler.invocation_id
  ]


def GenTests(api: TEST_DEPS):
  yield (
    api.test('unset')
  )
  yield (
    api.test('set') +
    api.scheduler(
      hostname='scheduler.example.com',
      job_id='some/job',
      invocation_id=12345,
    )
  )
