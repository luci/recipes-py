# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

DEPS = [
    'buildbucket',
    'cv',
]

from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api):
  assert api.cv.cl_owners == ['somename@chromium.org']


def GenTests(api):
  yield api.test(
      'simple',
      api.cv(run_mode=api.cv.DRY_RUN),
      api.buildbucket.try_build(
          change_number=123,
          tags=api.buildbucket.tags(cq_cl_owner='somename@chromium.org'),
      ),
      api.post_process(post_process.DropExpectation),
  )
