# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import rpc as rpc_pb2

DEPS = [
  'buildbucket',
  'json',
  'step',
]


def RunSteps(api):
  build = api.buildbucket.get(9016911228971028736)
  assert build.id == 9016911228971028736

  builds = api.buildbucket.get_multi([9016911228971028736, 9016911228971028737])
  assert set(builds.keys()) == {9016911228971028736, 9016911228971028737}

  # Legacy
  api.buildbucket.get_build('9016911228971028736', name='legacy_get')


def GenTests(api):
  yield (
      api.test('basic') +
      api.buildbucket.simulated_get(build_pb2.Build(
          id=9016911228971028736, status=common_pb2.SUCCESS,
      )) +
      api.buildbucket.simulated_get_multi([
        build_pb2.Build(id=9016911228971028736, status=common_pb2.SUCCESS),
        build_pb2.Build(id=9016911228971028737, status=common_pb2.SUCCESS),
      ]) +
      api.buildbucket.simulated_buildbucket_output(None, step_name='legacy_get')
  )


  yield (
      api.test('failed request') +
      api.step_data(
          'buildbucket.get',
          api.json.output_stream(
              json_format.MessageToDict(rpc_pb2.BatchResponse(
                  responses=[dict(error=dict(message='there was a problem'))],
              )),
          ),
        )
  )
