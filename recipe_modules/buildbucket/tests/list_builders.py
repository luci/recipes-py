# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2

DEPS = [
  'buildbucket'
]

def RunSteps(api):
  api.buildbucket.list_builders(
      'project', 'bucket', step_name='a step')

def GenTests(api):
  yield (
      api.test('basic') +
      api.buildbucket.simulated_list_builders(
          ['builder-1', 'builder-2'],
          step_name='a step')
  )
