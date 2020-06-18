# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'legacy_annotation',
  'proto',
  'step',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import step as step_pb2

def RunSteps(api):
  ret = api.legacy_annotation('sub annotation',
                              ['echo', '@@@BUILD_STEP@Hi Sub Annotation@@@'])
  api.step('print sub build',
           ['echo', api.proto.encode(ret.step.sub_build, 'JSONPB')])


def GenTests(api):
  yield (
    api.test('basic') +
    api.step_data('sub annotation', api.step.sub_build(
      build_pb2.Build(
        id=1,
        status=common_pb2.SUCCESS,
        steps=[
          step_pb2.Step(name='Hi Sub Annotation', status=common_pb2.SUCCESS),
        ]
      )
    ))
  )
