# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
from PB.go.chromium.org.luci.lucictx import sections as sections_pb2

DEPS = [
  'context',
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

  api.step('test with exonerate_unexpected_pass', api.resultdb.wrap(
      ['echo', 'suppose its a test'],
      exonerate_unexpected_pass=True,
  ))

  api.step('test with inv_properties', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    inv_properties=json.dumps({'key': 'value'}),
  ))

  api.step('test with inv_properties_file', api.resultdb.wrap(
    ['echo', 'suppose its a test'],
    inv_properties_file="properties.json",
  ))

  api.step(
      'test with inherit_sources',
      api.resultdb.wrap(['echo', 'suppose its a test'], inherit_sources=True))

  api.step(
      'test with sources',
      api.resultdb.wrap(
          ['echo', 'suppose its a test'],
          sources=json.dumps({
              'gitiles_commit': {
                  'host': 'chromium.googlesource.com',
                  'project': 'chromium/src',
                  'ref': 'refs/heads/main',
                  'commit_hash': '0011223344556677889900112233445566778899',
                  'position': 1234,
              }
          }),
      ))

  api.step(
      'test with sources_file',
      api.resultdb.wrap(
          ['echo', 'suppose its a test'],
          sources_file='sources.json',
      ))


def GenTests(api):
  yield api.test(
      'basic',
      api.context.luci_context(
          realm=sections_pb2.Realm(name='proj:realm'),
          resultdb=sections_pb2.ResultDB(
              current_invocation=sections_pb2.ResultDBInvocation(
                  name='invocations/inv',
                  update_token='token',
              ),
              hostname='rdbhost',
          )
      ),
  )
