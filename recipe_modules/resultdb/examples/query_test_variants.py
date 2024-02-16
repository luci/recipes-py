# Copyright 2024 The LUCI Authors. All rights reserved.
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
    'test_variant_status': Property(default=None, kind=str),
    'field_mask_paths': Property(default=None, kind=list),
}


def RunSteps(api, invocation, test_variant_status, field_mask_paths):
  api.resultdb.query_test_variants(
      [invocation],
      test_variant_status=test_variant_status,
      page_size=10,
      field_mask_paths=field_mask_paths,
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(invocation='invocations/build-8761170341278523313'),
      api.resultdb.query_test_variants(resultdb.QueryTestVariantsResponse()),
      api.post_process(DropExpectation),
  )
  yield api.test(
      'status_and_fields',
      api.properties(
          invocation='invocations/build-8761170341278523313',
          test_variant_status='UNEXPECTED',
          field_mask_paths=['results', 'sources_id'],
      ),
      api.resultdb.query_test_variants(resultdb.QueryTestVariantsResponse()),
      api.post_process(DropExpectation),
  )
