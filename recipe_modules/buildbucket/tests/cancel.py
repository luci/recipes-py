# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'buildbucket'
]

def RunSteps(api):
  api.buildbucket.cancel_build(
    1785294945718829, step_name='cancel_without_reason')
  api.buildbucket.cancel_build(
    6838835292664158, reason="Discarded!!", step_name='cancel_with_reason')
  try:
    api.buildbucket.cancel_build(
      'invalid.build.id.12345', step_name='invalid_build_id')
  except Exception as e:
    assert isinstance(e, ValueError)

def GenTests(api):
  def construct_batch_response(build_id, status):
    return builds_service_pb2.BatchResponse(
      responses=[
        dict(cancel_build=dict(
          id=build_id,
          status=status
        ))
      ]
    )

  yield (
      api.test('basic') +
      api.buildbucket.simulated_cancel_output(
        construct_batch_response(build_id=1785294945718829,
                                 status=common_pb2.CANCELED),
        step_name='cancel_without_reason') +
      api.buildbucket.simulated_cancel_output(
        construct_batch_response(build_id=6838835292664158,
                                 status=common_pb2.CANCELED),
        step_name='cancel_with_reason')
  )

  error_batch_response = builds_service_pb2.BatchResponse(
    responses=[
      dict(error=dict(
        code=123,
        message='some error message'
      ))
    ]
  )
  yield (
      api.test('error') +
      api.buildbucket.simulated_cancel_output(
        construct_batch_response(build_id=1785294945718829,
                                 status=common_pb2.CANCELED),
        step_name='cancel_without_reason') +
      api.buildbucket.simulated_cancel_output(
        error_batch_response,
        step_name='cancel_with_reason')
  )
