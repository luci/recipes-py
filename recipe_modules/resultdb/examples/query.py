# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from google.protobuf import json_format

from recipe_engine.post_process import (DropExpectation, StepSuccess,
  PropertyEquals)

from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2

DEPS = [
  'buildbucket',
  'resultdb',
  'step',
]


def RunSteps(api):
  inv_bundle = api.resultdb.query(
      inv_ids=api.resultdb.invocation_ids(
          ['invocations/chromium-swarm.appspot.com/deadbeef']),
      step_name='rdb query',
      variants_with_unexpected_results=True,
      merge=True,
      tr_fields=['tags'],
      test_regex="task-chromium-swarm.+",
  )
  if inv_bundle:
    pres = api.step.active_result.presentation
    pres.properties['inv_bundle'] = api.resultdb.serialize(
        inv_bundle, pretty=True)


def GenTests(api):
  inv_bundle = {
     'task-chromium-swarm.appspot.com-deadbeef': api.resultdb.Invocation(
        proto=invocation_pb2.Invocation(
            state=invocation_pb2.Invocation.FINALIZED
        ),
        test_results=[
          test_result_pb2.TestResult(
            test_id='ninja://chromium/tests:browser_tests/',
            expected=False,
            status=test_result_pb2.FAIL,
          ),
        ],
        test_exonerations=[
          test_result_pb2.TestExoneration(
            test_id='ninja://chromium/tests:browser_tests/',
            explanation_html='Known to be flaky',
          ),
        ],
     ),
  }
  yield (
      api.test('basic') +
      api.resultdb.query(
          step_name='rdb query',
          inv_bundle=inv_bundle) +
      api.post_process(StepSuccess, 'rdb query') +
      api.post_process(
          PropertyEquals,
          'inv_bundle',
          api.resultdb.serialize(inv_bundle, pretty=True)) +
      api.post_process(DropExpectation)
  )
