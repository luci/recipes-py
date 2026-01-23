# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.resultdb.examples import query_test_results as query_test_results_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb
from recipe_engine.post_process import DropExpectation

DEPS = [
    'resultdb',
    'recipe_engine/properties',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  string invocation = 1;
  string test_id_regexp = 2;
}
"""

PROPERTIES = query_test_results_pb.InputProperties

def RunSteps(api, props: query_test_results_pb.InputProperties):
  api.resultdb.query_test_results(
      [props.invocation],
      props.test_id_regexp,
      page_size=10,
      field_mask_paths=['status'],
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          query_test_results_pb.InputProperties(
              invocation='invocations/inv',
              test_id_regexp='checkdeps',
          )),
      api.resultdb.query_test_results(resultdb.QueryTestResultsResponse()),
      api.post_process(DropExpectation),
  )
