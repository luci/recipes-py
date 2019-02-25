# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'buildbucket',
  'cq',
  'step',
]


def RunSteps(api):
  api.step('no builds actually triggered', cmd=[])
  api.cq.record_triggered_builds(*[])
  assert api.cq.triggered_build_ids == []

  api.step('triggered some builds', cmd=[])
  api.cq.record_triggered_build_ids(1, 2)
  api.cq.record_triggered_builds(
      api.buildbucket.build_pb2.Build(id=22),
      api.buildbucket.build_pb2.Build(id=11))
  assert api.cq.triggered_build_ids == [1, 2, 22, 11]


def GenTests(api):
  yield api.test('example')
