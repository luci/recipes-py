# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process
from recipe_engine.config import List, Single, ConfigList, ConfigGroup
from recipe_engine.recipe_api import Property

DEPS = [
  'cipd',
  'platform',
  'step',
]


def RunSteps(api):
  api.step.empty(f'platform {api.cipd.platform}')


def GenTests(api):
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
