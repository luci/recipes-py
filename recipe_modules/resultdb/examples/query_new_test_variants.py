# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.resultdb.examples import query_new_test_variants as query_new_test_variants_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb
from recipe_engine.post_process import DropExpectation

DEPS = [
    'resultdb',
    'recipe_engine/properties',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  string invocation = 1;
  string baseline = 2;
}
"""

PROPERTIES = query_new_test_variants_pb.InputProperties


def RunSteps(api, props: query_new_test_variants_pb.InputProperties):
  api.resultdb.query_new_test_variants(
      props.invocation,
      props.baseline,
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          query_new_test_variants_pb.InputProperties(
              invocation='invocations/inv',
              baseline='projects/chromium/baselines/try:linux-rel',
          )),
      api.resultdb.query_new_test_variants(
          resultdb.QueryNewTestVariantsResponse()),
      api.post_process(DropExpectation),
  )
