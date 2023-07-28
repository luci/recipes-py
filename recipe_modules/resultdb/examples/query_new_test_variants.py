# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation
from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb

DEPS = [
    'resultdb',
    'recipe_engine/properties',
]

PROPERTIES = {
    'invocation': Property(default=None, kind=str),
    'baseline': Property(default=None, kind=str),
}


def RunSteps(api, invocation, baseline):
  api.resultdb.query_new_test_variants(
      invocation,
      baseline,
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          invocation='invocations/inv',
          baseline='projects/chromium/baselines/try:linux-rel',
      ),
      api.resultdb.query_new_test_variants(resultdb.QueryTestResultsResponse()),
      api.post_process(DropExpectation),
  )
