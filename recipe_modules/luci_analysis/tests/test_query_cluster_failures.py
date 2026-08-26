# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for query_cluster_failres."""
from __future__ import annotations

from PB.go.chromium.org.luci.analysis.proto.v1.clusters import DistinctClusterFailure

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    luci_analysis,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  luci_analysis: luci_analysis.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  luci_analysis: luci_analysis.TEST_API


def RunSteps(api: DEPS):
  parent = 'projects/chromium/clusters/rules/00000000000000000000ffffffffffff'
  api.assertions.assertEqual(
      api.luci_analysis.rule_name_to_cluster_name(
          'projects/chromium/rules/00000000000000000000ffffffffffff'), parent)

  with api.step.nest('nest_parent'):
    failures = api.luci_analysis.query_cluster_failures(parent)
    api.assertions.assertIsNotNone(failures)
    api.assertions.assertGreaterEqual(len(failures), 2)


def GenTests(api: TEST_DEPS):
  yield api.test(
      'base',
      api.luci_analysis.query_cluster_failures(
          [{
              'test_id': 'dummy_test_id',
              'variant': {
                  'def': {
                      'foo': 'bar',
                  }
              },
              'count': 2,
          },
           DistinctClusterFailure(
               **{
                   'test_id': 'dummy_test_id_2',
                   'variant': {
                       'def': {
                           'foo': 'bar2',
                       }
                   },
                   'count': 1,
               })],
          'projects/chromium/clusters/rules/00000000000000000000ffffffffffff',
          parent_step_name='nest_parent'),
  )
