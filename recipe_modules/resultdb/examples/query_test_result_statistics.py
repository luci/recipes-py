# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb
from PB.go.chromium.org.luci.resultdb.proto.v1 import test_result as test_result_pb2

DEPS = [
    'resultdb',
]


def RunSteps(api):
  api.resultdb.query_test_result_statistics()


def GenTests(api):
  yield api.test(
      'basic',
      api.resultdb.query_test_result_statistics(
          resultdb.QueryTestResultStatisticsResponse(total_test_results=5)),
      api.post_process(DropExpectation),
  )
