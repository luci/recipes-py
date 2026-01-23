#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_failure_rate."""
from __future__ import annotations

from PB.recipe_modules.recipe_engine.luci_analysis.tests import query_failure_rate_test as query_failure_rate_test_pb
from recipe_engine import post_process

DEPS = [
    'luci_analysis',
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]

INLINE_PROPERTIES_PROTO = """
message TestVariant {
  string test_id = 1 [json_name = "testId"];
  string variant_hash = 2 [json_name = "variantHash"];
}

message InputProperties {
  repeated TestVariant input_list = 1;
}
"""

PROPERTIES = query_failure_rate_test_pb.InputProperties


def RunSteps(api, props: query_failure_rate_test_pb.InputProperties):
  input_list = [
      {'testId': i.test_id, 'variantHash': i.variant_hash}
      for i in props.input_list
  ]
  api.luci_analysis.query_failure_rate(input_list)


def GenTests(api):
  query_failure_rate_results = [
      api.luci_analysis.generate_analysis(
          test_id='ninja://gpu:suite_1/test_one',
          expected_count=8,
          unexpected_count=2,
          flaky_verdict_counts=[3, 20],
      ),
      api.luci_analysis.generate_analysis(
          test_id='ninja://gpu:suite_2/test_one',
          expected_count=1,
          unexpected_count=9,
      ),
      api.luci_analysis.generate_analysis(
          test_id='ninja://gpu:suite_3/test_one',
          expected_count=9,
          unexpected_count=1,
      ),
      api.luci_analysis.generate_analysis(
          test_id='ninja://gpu:suite_3/test_two',
          expected_count=10,
          unexpected_count=0,
      ),
  ]

  yield api.test(
      'basic',
      api.properties(
          query_failure_rate_test_pb.InputProperties(
              input_list=[
                  query_failure_rate_test_pb.TestVariant(
                      test_id='ninja://gpu:suite_1/test_one',
                      variant_hash='88d12dbe8971eab5',
                  ),
                  query_failure_rate_test_pb.TestVariant(
                      test_id='ninja://gpu:suite_2/test_one',
                      variant_hash='88d12dbe8971fheu',
                  ),
                  query_failure_rate_test_pb.TestVariant(
                      test_id='ninja://gpu:suite_3/test_one',
                      variant_hash='98d12dbe8971eab5',
                  ),
                  query_failure_rate_test_pb.TestVariant(
                      test_id='ninja://gpu:suite_3/test_two',
                      variant_hash='88d12dbe8971eid5',
                  ),
                  query_failure_rate_test_pb.TestVariant(
                      test_id='ninja://gpu:suite_3/test_three',
                      variant_hash='88d12dbe8971eid5',
                  ),
              ],
          )),
      api.luci_analysis.query_failure_rate_results(query_failure_rate_results),
      api.post_process(
          post_process.LogContains,
          'query LUCI Analysis for failure rates.rpc call',
          'input',
          [
              'ninja://gpu:suite_1/test_one',
              'ninja://gpu:suite_2/test_one',
              'ninja://gpu:suite_3/test_one',
              'ninja://gpu:suite_3/test_two',
              'ninja://gpu:suite_3/test_three',
          ],
      ),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'empty_response',
      api.properties(
          query_failure_rate_test_pb.InputProperties(
              input_list=[
                  query_failure_rate_test_pb.TestVariant(
                      test_id='ninja://gpu:suite_1/test_one',
                      variant_hash='88d12dbe8971eab5',
                  ),
              ],
          )),
      api.step_data(
          'query LUCI Analysis for failure rates.rpc call',
          stdout=api.raw_io.output_text(api.json.dumps({})),
      ),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
