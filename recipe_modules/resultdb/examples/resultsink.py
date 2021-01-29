# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import (DropExpectation, StepCommandContains,
  DoesNotRunRE)

from PB.go.chromium.org.luci.resultdb.proto.v1 import invocation as invocation_pb2

DEPS = [
  'buildbucket',
  'resultdb',
  'step',
]


def RunSteps(api):
  api.step('test', api.resultdb.wrap(['echo', 'suppose its a test']))

  api.step('test with test_id_prefix', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    test_id_prefix='prefix',
  ))

  api.step('test with base_variant', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    base_variant={
      'bucket': 'ci',
      'builder': 'linux-rel',
    },
  ))

  api.step('test with test_location_base', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    test_location_base='//foo/bar',
  ))

  api.step('test with base_tag', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    base_tags=[
        ('step_name', 'pre test'),
    ],
  ))

  api.step('test with corece_negative_duration', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    coerce_negative_duration=True,
  ))

  api.step('test with include new invocation', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    include=True,
    realm='project:bucket',
  ))

  api.step('test with include new invocation default realm',
    api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    include=True,
  ))

  api.step('test with location_tags_file', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    location_tags_file='location_tags.json',
  ))


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(),
  )
