# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'assertions',
    'cv',
    'step',
]


def RunSteps(api):
  api.step('disallow reuse only for full run', cmd=None)
  api.assertions.assertFalse(api.cv.allowed_reuse_modes)
  with api.assertions.assertRaises(ValueError):
    api.cv.allow_reuse_for()  # must provide at least one modes
  api.cv.allow_reuse_for(api.cv.QUICK_DRY_RUN)
  api.assertions.assertListEqual(api.cv.allowed_reuse_modes, [
      api.cv.QUICK_DRY_RUN,
  ])
  api.cv.allow_reuse_for(api.cv.DRY_RUN, api.cv.FULL_RUN)
  api.assertions.assertListEqual(api.cv.allowed_reuse_modes,
                                 [api.cv.DRY_RUN, api.cv.FULL_RUN])


def GenTests(api):
  yield api.test('example')
