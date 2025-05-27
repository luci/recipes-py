# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb

DEPS = [
    'context',
    'resultdb',
]


def RunSteps(api):
  api.resultdb.query_test_result_statistics()


def GenTests(api):
  yield api.test(
      'basic',
      api.context.luci_context(
          resultdb=sections_pb2.ResultDB(
              current_invocation=sections_pb2.ResultDBInvocation(
                  name='invocations/inv',
                  update_token='token',
              ),
          )
      ),
      api.resultdb.query_test_result_statistics(
          resultdb.QueryTestResultStatisticsResponse(total_test_results=5)),
      api.post_process(DropExpectation),
  )
