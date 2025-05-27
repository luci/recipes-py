# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from recipe_engine import recipe_api

DEPS = [
  'buildbucket',
  'cq',
  'step',
]


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
def RunSteps(api):
  api.step('no builds actually triggered', cmd=[])
  api.cq.record_triggered_builds(*[])
  assert api.cq.triggered_build_ids == []

  api.step('triggered some builds', cmd=[])
  api.cq.record_triggered_build_ids(1, 2)
  api.cq.record_triggered_builds(Build(id=22), Build(id=11))
  assert api.cq.triggered_build_ids == [1, 2, 22, 11]


def GenTests(api):
  yield api.test('example')
