# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.cq.api.recipe.v1 import cq as cq_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

DEPS = [
  'assertions',
  'buildbucket',
  'cq',
  'properties',
  'step',
]


def RunSteps(api):
  if 'raises' in api.properties:
    with api.assertions.assertRaises(api.cq.CQInactive):
      api.cq.ordered_gerrit_changes
    return

  api.assertions.assertEqual(
      ' '.join(str(g.change) for g in api.cq.ordered_gerrit_changes),
      api.properties['expected_cls'])


def GenTests(api):
  yield (
    api.test('appropriate')
    + api.cq(full_run=True, gerrit_changes=[
        bb_common_pb2.GerritChange(
            host='x-review.example.com',
            change=123,
            patchset=4,
            project='xproject'),
        bb_common_pb2.GerritChange(
            host='y-review.example.com',
            change=789,
            patchset=4,
            project='yproject'),
      ],
    )
    + api.properties(expected_cls='123 789')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('with-deps')
    + api.cq(full_run=True, cls=[
        cq_pb2.CL(
            gerrit=bb_common_pb2.GerritChange(
                host='x-review.example.com',
                change=123,
                patchset=4,
                project='xproject'),
            deps=[1]),
        cq_pb2.CL(
            gerrit=bb_common_pb2.GerritChange(
                host='y-review.example.com',
                change=789,
                patchset=4,
                project='yproject'),
            deps=[]),
      ],
    )
    + api.properties(expected_cls='123 789')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('cq-run-cls-from-bb')
    + api.cq(full_run=True)
    + api.buildbucket.try_build(change_number=123)
    + api.properties(expected_cls='123')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('not-a-cq-run')
    + api.properties(raises=True)
    + api.post_process(post_process.DropExpectation)
  )
