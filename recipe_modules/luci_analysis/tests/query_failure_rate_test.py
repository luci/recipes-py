#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_failure_rate."""
from recipe_engine import post_process
from recipe_engine.config import Dict
from recipe_engine.config import List
from recipe_engine.recipe_api import Property

DEPS = [
    'luci_analysis',
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]

PROPERTIES = {
    'input_list': Property(kind=list),
}


def RunSteps(api, input_list):
  suite_to_failure_rate_per_suite = api.luci_analysis.query_failure_rate(
      input_list)


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
          input_list=[
              {
                  'testId': 'ninja://gpu:suite_1/test_one',
                  'variantHash': '88d12dbe8971eab5',
              },
              {
                  'testId': 'ninja://gpu:suite_2/test_one',
                  'variantHash': '88d12dbe8971fheu',
              },
              {
                  'testId': 'ninja://gpu:suite_3/test_one',
                  'variantHash': '98d12dbe8971eab5',
              },
              {
                  'testId': 'ninja://gpu:suite_3/test_two',
                  'variantHash': '88d12dbe8971eid5',
              },
              {
                  'testId': 'ninja://gpu:suite_3/test_three',
                  'variantHash': '88d12dbe8971eid5',
              },
          ],),
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
          input_list=[
              {
                  'testId': 'ninja://gpu:suite_1/test_one',
                  'variantHash': '88d12dbe8971eab5',
              },
          ],),
      api.step_data(
          'query LUCI Analysis for failure rates.rpc call',
          stdout=api.raw_io.output_text(api.json.dumps({})),
      ),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
