# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from PB.go.chromium.org.luci.common.proto.findings import findings as findings_pb
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    buildbucket,
    findings,
    properties,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  buildbucket: buildbucket.API
  findings: findings.API
  properties: properties.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  properties: properties.TEST_API

PROPERTIES = findings_pb.Location


def RunSteps(api: DEPS, expected_loc):
  location = findings_pb.Location()
  api.findings.populate_source_from_current_build(location)
  if expected_loc:
    api.assertions.assertEqual(location, expected_loc)


def GenTests(api: TEST_DEPS):
  yield (api.test('basic') + api.buildbucket.try_build(gerrit_changes=[
      common_pb2.GerritChange(
          host='example-review.googlesource.com',
          project='foo',
          change=123456,
          patchset=7),
  ]) + api.properties(
      findings_pb.Location(
          gerrit_change_ref=findings_pb.Location.GerritChangeReference(
              host='example-review.googlesource.com',
              project='foo',
              change=123456,
              patchset=7))) + api.post_process(post_process.DropExpectation))

  yield (api.test('no gerrit changes') + api.buildbucket.generic_build() +
         api.expect_exception('ValueError') + api.post_process(
             post_process.SummaryMarkdownRE,
             'current build input does not contain a gerrit change') +
         api.post_process(post_process.DropExpectation))

  yield (api.test('multiple gerrit changes') +
         api.buildbucket.try_build(gerrit_changes=[
             common_pb2.GerritChange(
                 host='example-review.googlesource.com',
                 project='foo',
                 change=123456,
                 patchset=7),
             common_pb2.GerritChange(
                 host='example-review.googlesource.com',
                 project='foo',
                 change=987654,
                 patchset=3),
         ]) + api.expect_exception('ValueError') + api.post_process(
             post_process.SummaryMarkdownRE,
             'current build input contains more than one gerrit changes') +
         api.post_process(post_process.DropExpectation))
