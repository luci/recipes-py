# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for generate_stability_response."""
from __future__ import annotations

from recipe_engine import post_process

DEPS = [
    'luci_analysis',
    'recipe_engine/json',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def RunSteps(api):
  # This is to get coverage of the test_api which is being used more extensively
  # outside this module
  api.step.empty('step')


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data(
          'step',
          stdout=api.raw_io.output_text(
              api.json.dumps(
                  api.luci_analysis.generate_stability_response([
                      api.luci_analysis.generate_stability_analysis(
                          test_id='ninja://failed_test/testA',
                          failure_rate_is_met=False,
                          flake_rate_is_met=False,
                          run_flaky_verdicts_1wd=0,
                          run_flaky_verdicts_12h=0,
                      ),
                      api.luci_analysis.generate_stability_analysis(
                          test_id='ninja://failed_test/testB',
                          failure_rate_is_met=False,
                          flake_rate_is_met=False,
                          run_flaky_verdicts_1wd=0,
                          run_flaky_verdicts_12h=0,
                      ),
                  ])))),
      api.post_process(post_process.DropExpectation),
  )
