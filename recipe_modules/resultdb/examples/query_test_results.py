# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation
from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.resultdb.proto.v1 import resultdb

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    'resultdb',
    'recipe_engine/properties',
]

PROPERTIES = {
  'invocation': Property(default=None, kind=str),
  'test_id_regexp': Property(default=None, kind=str),
}

def RunSteps(api, invocation, test_id_regexp):
  api.resultdb.query_test_results(
      [invocation],
      test_id_regexp,
      page_size=10,
      field_mask_paths=['status'],
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          invocation='invocations/inv',
          test_id_regexp='checkdeps',
      ),
      api.resultdb.query_test_results(resultdb.QueryTestResultsResponse()),
      api.post_process(DropExpectation),
  )
