# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

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
      api.properties(
        buildername='example_builder',
        buildnumber=123,
        buildbucket={
            'build': {
                'tags': [
                    ('buildset:patch/gerrit/chromium-review.googlesource.com/'
                    '123/10001'),
                    'undesired:should-not-be-in-expectations',
                ],
            },
        },
      )
  )
  yield (
      api.test('gitiles commit') +
      api.properties(
        buildername='example_builder',
        buildnumber=123,
        buildbucket={
            'build': {
                'tags': [
                    ('buildset:commit/gitiles/chromium.googlesource.com/'
                     'project/+/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
                    'gitiles_ref:refs/heads/master',
                ],
            },
        },
      )
  )
  yield (
      api.test('custom buildset') +
      api.properties(
        buildername='example_builder',
        buildnumber=123,
        buildbucket={
          'build': {
            'tags': [
              'buildset:x',
            ],
          },
        },
      )
  )
  yield (
      api.test('basic_experimental') +
      api.properties(buildername='experimental_builder', buildnumber=123) +
      api.runtime(is_luci=True, is_experimental=True)
  )
  yield (
      api.test('request experimental') +
      api.properties(
          buildername='example_builder',
          buildnumber=123,
          request_experimental=True,
      )
  )
