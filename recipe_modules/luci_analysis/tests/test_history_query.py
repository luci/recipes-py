# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_failure_rate."""
from recipe_engine import post_process

from google.protobuf import timestamp_pb2
from PB.go.chromium.org.luci.analysis.proto.v1 import common as common_pb2
from PB.go.chromium.org.luci.analysis.proto.v1 import predicate as predicate_pb2
from PB.go.chromium.org.luci.analysis.proto.v1 import test_history
from PB.go.chromium.org.luci.analysis.proto.v1 import test_verdict

PYTHON_VERSION_COMPATIBILITY = "PY3"

DEPS = [
    'luci_analysis',
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def RunSteps(api):
  with api.step.nest('nest_parent'):
    test_id = 'ninja://gpu:suite_1/test_one'
    next_page_token = None
    exit_loop = False
    while not exit_loop:
      _, next_page_token = api.luci_analysis.query_test_history(
          test_id,
          sub_realm='try',
          variant_predicate=predicate_pb2.VariantPredicate(
              contains={'def': {
                  'builder': 'some-builder'
              }}),
          partition_time_range=common_pb2.TimeRange(
              earliest=timestamp_pb2.Timestamp(seconds=1000),
              latest=timestamp_pb2.Timestamp(seconds=2000)),
          submitted_filter=common_pb2.ONLY_SUBMITTED,
          page_size=1000,
          page_token=next_page_token,
      )
      if not next_page_token:
        exit_loop = True


def GenTests(api):
  res = test_history.QueryTestHistoryResponse(
      verdicts=[
          test_verdict.TestVerdict(
              test_id='ninja://gpu:suite_1/test_one',
              variant_hash='dummy_hash',
              invocation_id='invocations/id',
              status=test_verdict.TestVerdictStatus.EXPECTED,
          ),
      ],
      next_page_token='dummy_token')
  res2 = test_history.QueryTestHistoryResponse()
  test_id = 'ninja://gpu:suite_1/test_one'
  yield api.test(
      'basic',
      api.luci_analysis.query_test_history(
          res, test_id, parent_step_name='nest_parent'),
      api.luci_analysis.query_test_history(
          res2, test_id, parent_step_name='nest_parent', step_iteration=2),
      api.post_process(post_process.DropExpectation))
