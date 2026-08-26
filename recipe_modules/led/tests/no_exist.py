# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    led,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  led: led.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  led: led.TEST_API


def RunSteps(api: DEPS):
  try:
    api.led('get-builder', 'fake/bucket:no-exist')
    assert False, 'get-builder found a build'  # pragma: no cover
  except api.step.StepFailure:
    pass

  try:
    api.led('get-build', 123456789)
    assert False, 'get-build found a build'  # pragma: no cover
  except api.step.StepFailure:
    pass

  try:
    api.led('get-swarm', 'deadbeef')
    assert False, 'get-swarm found a build'  # pragma: no cover
  except api.step.StepFailure:
    pass


def GenTests(api: TEST_DEPS):
  yield api.test(
      'find nothing',
      api.led.mock_get_builder(None, 'fake', 'bucket', 'no-exist'),
      api.led.mock_get_build(None, 123456789),
      api.led.mock_get_swarm(None, 'deadbeef'),
  )
