# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from PB.go.chromium.org.luci.common.proto.findings import findings as findings_pb
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'assertions',
    'buildbucket',
    'findings',
    'properties',
]

PROPERTIES = findings_pb.Location


def RunSteps(api, expected_loc):
  location = findings_pb.Location()
  api.findings.populate_source_from_current_build(location)
  if expected_loc:
    api.assertions.assertEqual(location, expected_loc)


def GenTests(api):
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
