# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.resultdb.examples import query_new_test_variants as query_new_test_variants_pb
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb
from recipe_engine.post_process import DropExpectation

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    properties,
    resultdb as resultdb_rm,
)


@dataclass
class DEPS(RecipeScriptApi):
  properties: properties.API
  resultdb: resultdb_rm.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API
  resultdb: resultdb_rm.TEST_API

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  string invocation = 1;
  string baseline = 2;
}
"""

PROPERTIES = query_new_test_variants_pb.InputProperties


def RunSteps(api: DEPS, props: query_new_test_variants_pb.InputProperties):
  api.resultdb.query_new_test_variants(
      props.invocation,
      props.baseline,
  )


def GenTests(api: TEST_DEPS):
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
