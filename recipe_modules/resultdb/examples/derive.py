# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import json_format

from recipe_engine.post_process import (DropExpectation, StepSuccess,
  PropertyEquals)

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import test_result as test_result_pb2

DEPS = [
  'buildbucket',
  'resultdb',
  'step',
]


def RunSteps(api):
  test_results = api.resultdb.chromium_derive_merge(
      step_name='rdb chromium-derive',
      swarming_host='chromium-swarm.appspot.com',
      task_ids=['deadbeef'],
      variants_with_unexpected_results=True,
  )
  pres = api.step.active_result.presentation
  pres.properties['results'] = serialize_messages(test_results)


def GenTests(api):
  yield (
    api.test('basic') +
    api.post_process(StepSuccess, 'rdb chromium-derive') +
    api.post_process(PropertyEquals, 'results', serialize_messages([])) +
    api.post_process(DropExpectation)
  )

  test_results = [
    test_result_pb2.TestResult(
      test_path='gn://chromium/tests:browser_tests/',
      expected=False,
      status=test_result_pb2.FAIL,
    ),
  ]
  yield (
    api.test('simulated') +
    api.resultdb.chromium_derive(
      step_name='rdb chromium-derive',
      results={ None: test_results }) +
    api.post_process(StepSuccess, 'rdb chromium-derive') +
    api.post_process(
        PropertyEquals, 'results', serialize_messages(test_results)) +
    api.post_process(DropExpectation)
  )


def serialize_messages(messages):
  return json.dumps([json_format.MessageToDict(m) for m in messages])
