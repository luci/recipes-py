# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'buildbucket',
    'cv',
    'step',
]

from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api):
  api.step('no builds actually triggered', cmd=[])
  api.cv.record_triggered_builds(*[])
  assert api.cv.triggered_build_ids == []

  api.step('triggered some builds', cmd=[])
  api.cv.record_triggered_build_ids(1, 2)
  api.cv.record_triggered_builds(Build(id=22), Build(id=11))
  assert api.cv.triggered_build_ids == [1, 2, 22, 11]


def GenTests(api):
  yield api.test('example')
