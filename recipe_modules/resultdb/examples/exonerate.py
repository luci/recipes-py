# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import (DropExpectation, StepSuccess,
                                        DoesNotRun)

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    'context',
    'json',
    'properties',
    'resultdb',
    'step',
]

test_exonerations = [
    test_result_pb2.TestExoneration(
        test_id='ninja://chromium/tests:browser_tests/t1',
        variant={'def': {
            'key1': 'value1'
        }},
        explanation_html='Failed in without patch step',
    ),
    test_result_pb2.TestExoneration(
        test_id='ninja://chromium/tests:browser_tests/t2',
        variant={'def': {
            'key2': 'value2'
        }},
        explanation_html='Failed in without patch step',
    )
]


def RunSteps(api):
  api.resultdb._BATCH_SIZE = api.properties.get('batch_size', 500)
  api.resultdb.exonerate(
      test_exonerations=api.properties.get('test_exonerations',
                                           test_exonerations),
      step_name='exonerate without patch failures')


def GenTests(api):
  rdb_luci_context = sections_pb2.ResultDB(
      current_invocation=sections_pb2.ResultDBInvocation(
          name='invocations/build:8945511751514863184',
          update_token='token',
      ),
      hostname='rdbhost',
  )
  yield api.test(
      'exonerate',
      api.context.luci_context(
          realm=sections_pb2.Realm(name='chromium:ci'),
          resultdb=rdb_luci_context,
      ),
      api.post_process(StepSuccess, 'exonerate without patch failures'),
      api.post_process(DropExpectation))

  yield api.test(
      'exonerate in multiple batches', api.properties(batch_size=1),
      api.context.luci_context(
          realm=sections_pb2.Realm(name='chromium:ci'),
          resultdb=rdb_luci_context,
      ),
      api.post_process(StepSuccess, 'exonerate without patch failures'),
      api.post_process(StepSuccess,
                       'exonerate without patch failures.batch (0)'),
      api.post_process(StepSuccess,
                       'exonerate without patch failures.batch (1)'),
      api.post_process(DropExpectation))

  yield api.test(
      'no-op', api.properties(test_exonerations=[]),
      api.context.luci_context(
          realm=sections_pb2.Realm(name='chromium:ci'),
          resultdb=rdb_luci_context,
      ),
      api.post_process(DoesNotRun, 'exonerate without patch failures'),
      api.post_process(DropExpectation))
