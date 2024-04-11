# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process, recipe_api

DEPS = [
  'buildbucket',
  'cq',
]


from PB.go.chromium.org.luci.buildbucket.proto.build import Build


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api):
  assert api.cq.cl_group_key == 'changes-on-trivial-rebase', api.cq.cl_group_key
  assert api.cq.equivalent_cl_group_key == 'sticky-on-trivial-rebase', api.cq.equivalent_cl_group_key


def GenTests(api):
  yield api.test('simple',
    api.cq(run_mode=api.cq.DRY_RUN),
    api.buildbucket.try_build(
      change_number=123,
      tags=api.buildbucket.tags(
      cq_cl_group_key='changes-on-trivial-rebase',
      cq_equivalent_cl_group_key='sticky-on-trivial-rebase'),
    ),
    api.post_process(post_process.DropExpectation),
  )
