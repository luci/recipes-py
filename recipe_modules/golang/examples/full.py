# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'golang',
    'platform',
    'step',
]


def RunSteps(api):
  with api.golang(version='6.6.6'):
    api.step('go', ['build', '.'])


def GenTests(api):
  for platform in ('linux', 'mac', 'win'):
    yield (
        api.test(platform) +
        api.platform.name(platform))
