# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process
from recipe_engine.config import List, Single, ConfigList, ConfigGroup
from recipe_engine.recipe_api import Property

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    cipd,
    platform,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  cipd: cipd.API
  platform: platform.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  platform: platform.TEST_API


def RunSteps(api: DEPS):
  api.step.empty(f'platform {api.cipd.platform}')


def GenTests(api: TEST_DEPS):
  def test(cipd_platform, os, bits, arch='intel'):
    return api.test(
        cipd_platform,
        api.platform(os, bits, arch),
        api.post_process(post_process.MustRun, f'platform {cipd_platform}'),
        api.post_process(post_process.DropExpectation),
        status='SUCCESS',
    )

  yield test('linux-amd64', 'linux', 64)
  yield test('linux-386', 'linux', 32)
  yield test('linux-arm64', 'linux', 64, arch='arm')
  yield test('linux-armv6l', 'linux', 32, arch='arm')

  yield test('mac-amd64', 'mac', 64)
  yield test('mac-arm64', 'mac', 64, arch='arm')

  yield test('windows-amd64', 'win', 64)
  yield test('windows-386', 'win', 32)
  yield test('windows-arm64', 'win', 64, arch='arm')
