#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_failure_rate."""
from __future__ import annotations

from PB.recipe_modules.recipe_engine.luci_analysis.tests import query_failure_rate_test as query_failure_rate_test_pb
from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    json,
    luci_analysis,
    properties,
    raw_io,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  json: json.API
  luci_analysis: luci_analysis.API
  properties: properties.API
  raw_io: raw_io.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  json: json.TEST_API
  luci_analysis: luci_analysis.TEST_API
  properties: properties.TEST_API
  raw_io: raw_io.TEST_API

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


def RunSteps(api: DEPS, props: query_failure_rate_test_pb.InputProperties):
  input_list = [
      {'testId': i.test_id, 'variantHash': i.variant_hash}
      for i in props.input_list
  ]
  api.luci_analysis.query_failure_rate(input_list)


def GenTests(api: TEST_DEPS):
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
