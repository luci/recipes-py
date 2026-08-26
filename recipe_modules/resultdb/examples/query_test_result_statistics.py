# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    context,
    resultdb as resultdb_rm,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  resultdb: resultdb_rm.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  context: context.TEST_API
  resultdb: resultdb_rm.TEST_API


def RunSteps(api: DEPS):
  api.resultdb.query_test_result_statistics()


def GenTests(api: TEST_DEPS):
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
