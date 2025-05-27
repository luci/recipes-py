#!/usr/bin/env vpython3
# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_stability."""
from __future__ import annotations

from recipe_engine import post_process
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
  analysis, criteria = api.luci_analysis.query_stability(input_list, "chromeos")
  api.assertions.assertGreaterEqual(len(analysis), 1)
  api.assertions.assertIsNotNone(criteria)


def GenTests(api):
  input_list = api.luci_analysis.query_stability_example_input()
  output = api.luci_analysis.query_stability_example_output()

  yield api.test(
      'basic',
      api.properties(input_list=input_list),
      api.step_data(
          'query LUCI Analysis for stability.rpc call',
          stdout=api.raw_io.output_text(api.json.dumps(output)),
      ),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS')

  yield api.test(
      'step_failure',
      api.properties(input_list=input_list),
      api.step_data(
          'query LUCI Analysis for stability.rpc call',
          stdout=api.raw_io.output_text(api.json.dumps({})),
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE')
