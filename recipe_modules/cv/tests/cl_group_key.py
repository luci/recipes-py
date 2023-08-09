# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'buildbucket',
    'cv',
]

from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api):
  assert api.cv.cl_group_key == 'changes-on-trivial-rebase', api.cv.cl_group_key
  assert api.cv.equivalent_cl_group_key == 'sticky-on-trivial-rebase', (
      api.cv.equivalent_cl_group_key)


def GenTests(api):
  yield api.test(
      'simple',
      api.cv(run_mode=api.cv.DRY_RUN),
      api.buildbucket.try_build(
          change_number=123,
          tags=api.buildbucket.tags(
              cq_cl_group_key='changes-on-trivial-rebase',
              cq_equivalent_cl_group_key='sticky-on-trivial-rebase'),
      ),
      api.post_process(post_process.DropExpectation),
  )
