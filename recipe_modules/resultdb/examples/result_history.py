# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.resultdb.proto.v1 import predicate
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2

DEPS = [
    'resultdb',
]


def RunSteps(api):
  api.resultdb.get_test_result_history(
      realm='chromium:try',
      test_id_regexp='test_id_1|test_id_2',
      variant_predicate=predicate.VariantPredicate(
          contains={'def': {
              'builder': 'builder1'
          }}),
      page_token="1")


def GenTests(api):
  yield api.test(
      'basic',
      api.resultdb.get_test_result_history(
          resultdb.GetTestResultHistoryResponse(
              entries=[
                  resultdb.GetTestResultHistoryResponse.Entry(
                      result=test_result_pb2.TestResult(
                          test_id='ninja://chromium/tests:browser_tests/',
                          expected=False,
                          status=test_result_pb2.FAIL,
                      ),),
              ],)),
      api.post_process(DropExpectation),
  )
