# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    step,
    swarming,
)


@dataclass
class DEPS(RecipeScriptApi):
  step: step.API
  swarming: swarming.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  swarming: swarming.TEST_API


def RunSteps(api: DEPS):
  logs = api.step(cmd=None, name='task_info').presentation.logs
  logs['bot_id'] = [api.swarming.bot_id]
  logs['task_id'] = [api.swarming.task_id]
  logs['swarming_server'] = [api.swarming.current_server]


def GenTests(api: TEST_DEPS):
  yield api.test('simulated') + api.swarming.properties()
