# Copyright 2022 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.led.properties import InputProperties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    led,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  led: led.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


def RunSteps(api: DEPS):
  api.led.trigger_builder('chromium', 'ci', 'Foo Tester',
                          {'swarm_hashes': {
                              'bar': 'deadbeef'
                          }})


def GenTests(api: TEST_DEPS):
  led_run_id = 'led/user_example.com/deadbeef'
  yield api.test(
      'trigger',
      api.properties(
          **{'$recipe_engine/led': InputProperties(led_run_id=led_run_id)}))
