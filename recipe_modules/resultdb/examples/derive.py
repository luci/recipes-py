# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import json_format

from recipe_engine.post_process import (DropExpectation, StepSuccess,
  PropertyEquals)

from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import invocation as invocation_pb2
from PB.go.chromium.org.luci.resultdb.proto.rpc.v1 import test_result as test_result_pb2

DEPS = [
  'buildbucket',
  'resultdb',
  'step',
]


def RunSteps(api):
  inv_bundle = api.resultdb.chromium_derive(
      step_name='rdb chromium-derive',
      swarming_host='chromium-swarm.appspot.com',
      task_ids=['deadbeef'],
      variants_with_unexpected_results=True,
  )
  pres = api.step.active_result.presentation
  pres.properties['inv_bundle'] = api.resultdb.serialize(
      inv_bundle, pretty=True)


def GenTests(api):
  yield (
    api.test('basic') +
    api.post_process(StepSuccess, 'rdb chromium-derive') +
    api.post_process(PropertyEquals, 'inv_bundle', api.resultdb.serialize({})) +
    api.post_process(DropExpectation)
  )

  inv_bundle = {
     'invid': api.resultdb.Invocation(
        proto=invocation_pb2.Invocation(
            state=invocation_pb2.Invocation.COMPLETED
        ),
        test_results=[
          test_result_pb2.TestResult(
            test_path='ninja://chromium/tests:browser_tests/',
            expected=False,
            status=test_result_pb2.FAIL,
          ),
        ],
        test_exonerations=[
          test_result_pb2.TestExoneration(
            test_path='ninja://chromium/tests:browser_tests/',
            explanation_markdown='Known to be flaky',
          ),
        ],
     ),
  }
  yield (
    api.test('simulated') +
    api.resultdb.chromium_derive(
      step_name='rdb chromium-derive',
      results=inv_bundle) +
    api.post_process(StepSuccess, 'rdb chromium-derive') +
    api.post_process(
        PropertyEquals,
        'inv_bundle',
        api.resultdb.serialize(inv_bundle, pretty=True)) +
    api.post_process(DropExpectation)
  )
