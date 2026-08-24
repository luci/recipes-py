# Copyright 2016 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that daemons that hang on to STDOUT can't cause the engine to hang."""

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
  api.step(
      'bad daemon',
      ['python3',
       api.resource('win.py' if api.platform.is_win else 'unix.py')])


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
  yield api.test('basic_win') + api.platform(name='win', bits=64)
