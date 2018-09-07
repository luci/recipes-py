# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating the buildbucket recipe module."""

DEPS = [
  'buildbucket',
  'platform',
  'properties',
  'raw_io',
  'step',
]


def RunSteps(api):
  build = api.buildbucket.build
  if build.builder.bucket == 'try':
    assert build.builder.project == 'proj'
    assert build.builder.builder == 'try-builder'
    assert '-review' in build.input.gerrit_changes[0].host
  elif build.builder.bucket == 'ci':
    assert build.builder.project == 'proj-internal'
    assert build.builder.builder == 'ci-builder'
    gm = build.input.gitiles_commit
    assert 'chrome-internal.googlesource.com' == gm.host
    assert 'repo' == gm.project
  else:
    return

  # Note: this is not needed when running on LUCI. Buildbucket will use the
  # default account associated with the task.
  api.buildbucket.use_service_account_key('some-fake-key.json')

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
  build_tags2 = {'master': 'someother.master.url', 'builder': 'some_builder'}
  build_parameters_mac = build_parameters.copy()
  build_parameters_mac['builder_name'] = 'mac_perf_bisect'
  example_bucket = 'master.user.username'

  put_build_result = api.buildbucket.put(
      [{'bucket': example_bucket,
        'parameters': build_parameters,
        'tags': build_tags},
       {'bucket': example_bucket,
        'parameters': build_parameters_mac,
        'tags': build_tags2}])

  new_job_id = put_build_result.stdout['builds'][0]['id']

  get_build_result = api.buildbucket.get_build(new_job_id)
  if get_build_result.stdout['build']['status'] == 'SCHEDULED':
    api.buildbucket.cancel_build(new_job_id)

  # Switching hostname for expectations coverage only.
  api.buildbucket.set_buildbucket_host('cr-buildbucket-test.appspot.com')


def GenTests(api):
  mock_buildbucket_multi_response ="""
    {
      "builds":[{
       "status": "SCHEDULED",
       "created_ts": "1459200369835900",
       "bucket": "user.username",
       "result_details_json": "null",
       "status_changed_ts": "1459200369835930",
       "created_by": "user:username@example.com",
       "updated_ts": "1459200369835940",
       "utcnow_ts": "1459200369962370",
       "parameters_json": "{\\"This_has_been\\": \\"removed\\"}",
       "id": "9016911228971028736"
      }, {
       "status": "SCHEDULED",
       "created_ts": "1459200369835999",
       "bucket": "user.username",
       "result_details_json": "null",
       "status_changed_ts": "1459200369835988",
       "created_by": "user:username@example.com",
       "updated_ts": "1459200369835944",
       "utcnow_ts": "1459200369962377",
       "parameters_json": "{\\"This_has_been\\": \\"removed\\"}",
       "id": "9016911228971328738"
      }
       ],
     "kind": "buildbucket#resourcesItem",
     "etag": "\\"8uCIh8TRuYs4vPN3iWmly9SJMqw\\""
   }
  """
  mock_buildbucket_single_response = """
    {
      "build":{
       "status": "SCHEDULED",
       "created_ts": "1459200369835900",
       "bucket": "user.username",
       "result_details_json": "null",
       "status_changed_ts": "1459200369835930",
       "created_by": "user:username@example.com",
       "updated_ts": "1459200369835940",
       "utcnow_ts": "1459200369962370",
       "parameters_json": "{\\"This_has_been\\": \\"removed\\"}",
       "id": "9016911228971028736"
       },
     "kind": "buildbucket#resourcesItem",
     "etag": "\\"8uCIh8TRuYs4vPN3iWmly9SJMqw\\""
   }
  """
  yield (api.test('basic-try') +
         api.buildbucket.try_build(
             project='proj',
             builder='try-builder',
             git_repo='https://chrome-internal.googlesource.com/a/repo.git') +
         api.step_data(
             'buildbucket.put',
             stdout=api.raw_io.output_text(mock_buildbucket_multi_response)) +
         api.step_data(
             'buildbucket.get',
             stdout=api.raw_io.output_text(mock_buildbucket_single_response)))
  yield (api.test('basic-ci-win') +
         api.buildbucket.ci_build(
             project='proj-internal',
             bucket='ci',
             builder='ci-builder',
             git_repo='https://chrome-internal.googlesource.com/a/repo.git') +
         api.step_data(
             'buildbucket.put',
             stdout=api.raw_io.output_text(mock_buildbucket_multi_response)) +
         api.step_data(
             'buildbucket.get',
             stdout=api.raw_io.output_text(mock_buildbucket_single_response)) +
         api.platform('win', 32))

  yield (api.test('no_properties'))
