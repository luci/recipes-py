# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    platform,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  platform: platform.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  platform: platform.TEST_API


def RunSteps(api: DEPS):
  step_result = api.step('platform things', cmd=None)
  step_result.presentation.logs['name'] = [api.platform.name]
  step_result.presentation.logs['bits'] = [str(api.platform.bits)]
  step_result.presentation.logs['arch'] = [api.platform.arch]
  step_result.presentation.logs['cpu_count'] = [str(api.platform.cpu_count)]
  step_result.presentation.logs['memory'] = [str(api.platform.total_memory)]
  if api.platform.name == 'win':
    assert api.platform.is_win
    assert not api.platform.is_mac
    assert not api.platform.is_linux
  elif api.platform.name == 'linux':
    assert not api.platform.is_win
    assert not api.platform.is_mac
    assert api.platform.is_linux


def GenTests(api: TEST_DEPS):
  yield api.test('linux64') + api.platform('linux', 64)
  yield api.test('mac64') + api.platform('mac', 64)
  yield api.test('win32') + api.platform('win', 32)
  yield api.test('arm64') + api.platform('linux', 64, 'arm')
