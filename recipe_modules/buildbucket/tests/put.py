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
              'command': ('src/tools/perf/run_benchmark -v '
                          '--browser=release --output-format=chartjson '
                          '--also-run-disabled-tests speedometer'),
              'good_revision': '351045',
              'gs_bucket': 'chrome-perf',
              'max_time_minutes': '20',
              'metric': 'Total/Total',
              'recipe_tester_name': 'linux_perf_bisect',
              'repeat_count': '10',
              'test_type': 'perf'
          },
      }
  }

  build_tags = {'master': 'overriden.master.url',
                'builder': 'overriden_builder'}

  api.buildbucket.put(
      [{'bucket': example_bucket,
        'parameters': build_parameters,
        'tags': build_tags}])


def GenTests(api):
  yield (
      api.test('basic') +
      api.properties(buildername='example_builder', buildnumber=123)
  )
  yield (
      api.test('basic_experimental') +
      api.properties(buildername='experimental_builder', buildnumber=123) +
      api.runtime(is_luci=True, is_experimental=True)
  )
