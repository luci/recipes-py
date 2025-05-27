# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

DEPS = [
    'buildbucket',
    'cv',
]


def RunSteps(api):
  assert api.cv.attempt_key == 'attempt-key', api.cv.attempt_key


def GenTests(api):
  yield api.test(
      'simple',
      api.cv(run_mode=api.cv.DRY_RUN),
      api.buildbucket.try_build(
          change_number=123,
          tags=api.buildbucket.tags(cq_attempt_key='attempt-key'),
      ),
      api.post_process(post_process.DropExpectation),
  )
