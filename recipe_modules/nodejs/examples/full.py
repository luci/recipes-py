# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    nodejs,
    platform,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  nodejs: nodejs.API
  platform: platform.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  platform: platform.TEST_API


def RunSteps(api: DEPS):
  with api.nodejs(version='17.9.9'):
    api.step('npm', ['npm', 'version'])
  with api.nodejs(version='18.0.0'):
    api.step('npm', ['npm', 'version'])
  with api.nodejs(version='18.0.666'):
    api.step('npm', ['npm', 'version'])
  with api.nodejs(version='23.0.0'):
    api.step('npm', ['npm', 'version'])


def GenTests(api: TEST_DEPS):
  for platform in ('linux', 'mac', 'win'):
    yield (
        api.test(platform) +
        api.platform.name(platform))
