# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
  'buildbucket',
  'properties',
  'runtime',
]


def RunSteps(api):
  example_bucket = 'master.user.username'

  build_parameters = {
      'builder_name': 'linux_perf_bisect',
      'properties': {
          'bisect_config': {
              'bad_revision': '351054',
              'bug_id': 537649,
          },
      }
  }

  build_tags = {'master': 'overriden.master.url',
                'builder': 'overriden_builder',
                'new-and-custom': 'tag',
                'undesired': None}

  build = {'bucket': example_bucket,
           'parameters': build_parameters,
           'tags': build_tags}

  if api.properties.get('request_experimental'):
    build['experimental'] = True

  api.buildbucket.put([build])


def GenTests(api):
  yield (
      api.test('basic') +
      api.buildbucket.try_build(tags=api.buildbucket.tags(
        undesired='should-not-be-in-expectations',
      ))
  )
  yield (
      api.test('gitiles commit') +
      api.buildbucket.ci_build()
  )
  yield (
      api.test('custom buildset') +
      api.buildbucket.build(build_pb2.Build(
          id=9016911228971028736,
          tags=api.buildbucket.tags(buildset='custom'),
      ))
  )
  yield (
      api.test('basic_experimental') +
      api.buildbucket.ci_build() +
      api.runtime(is_experimental=True)
  )
  yield (
      api.test('request experimental') +
      api.buildbucket.ci_build() +
      api.properties(request_experimental=True)
  )
