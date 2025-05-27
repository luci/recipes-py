# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

DEPS = [
    'assertions',
]


def RunSteps(api):
  api.assertions.assertCountEqual([0, 1], (1, 0))


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
