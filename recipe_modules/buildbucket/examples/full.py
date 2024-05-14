# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file is a recipe demonstrating the buildbucket recipe module."""

import copy

from recipe_engine import recipe_api
from recipe_engine.post_process import DropExpectation

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'buildbucket',
    'json',
    'platform',
    'properties',
    'raw_io',
    'runtime',
    'step',
]


@recipe_api.ignore_warnings('recipe_engine/SET_BUILDBUCKET_HOST_DEPRECATED')
def RunSteps(api):
  build = api.buildbucket.build
  if build.builder.bucket == 'try':
    assert build.builder.project == 'proj'
    assert build.builder.builder == 'try-builder'
    assert '-review' in build.input.gerrit_changes[0].host
    assert build.input.gitiles_commit.id == 'a' * 40
    assert (build.input.gitiles_commit.project ==
            build.input.gerrit_changes[0].project)
  elif build.builder.bucket == 'ci':
    assert build.builder.project == 'proj-internal'
    assert build.builder.builder == 'ci-builder'
    gm = build.input.gitiles_commit
    assert 'chrome-internal.googlesource.com' == gm.host
    assert 'repo' == gm.project
    assert len(build.tags) == 2
    assert build.tags[0].key == 'user_agent'
    assert build.tags[0].value == 'cq'
    assert build.tags[1].key == 'user_agent'
    assert build.tags[1].value == 'recipe'
  else:
    return

  # Note: this is not needed when running on LUCI. Buildbucket will use the
  # default account associated with the task.
  api.buildbucket.use_service_account_key('some-fake-key.json')

  example_bucket = 'main.user.username'
  linux_req = api.buildbucket.schedule_request(
      builder='linux_perf_bisect',
      bucket=example_bucket,
      swarming_parent_run_id=api.properties.get('swarming_parent_run_id'),
      properties={
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
      })

  build_tags = {'main': 'overriden.main.url',
                'builder': 'overriden_builder'}
  build_tags2 = {'main': 'someother.main.url', 'builder': 'some_builder'}
  mac_req = copy.deepcopy(linux_req)
  mac_req.builder.builder = 'mac_perf_bisect'

  # Setting values for expectations coverage only, also tests host context.
  api.buildbucket.set_buildbucket_host('cr-buildbucket-test.appspot.com')
  assert api.buildbucket.host == 'cr-buildbucket-test.appspot.com'

  with api.buildbucket.with_host('cr-buildbucket-test2.appspot.com'):
    assert api.buildbucket.host == 'cr-buildbucket-test2.appspot.com'
    schedule_result = api.buildbucket.schedule([linux_req, mac_req])
  assert api.buildbucket.host == 'cr-buildbucket-test.appspot.com'

  bld = api.buildbucket.get(schedule_result[0].id)
  api.buildbucket.cancel_build(schedule_result[0].id)

  assert not api.buildbucket.build.output.HasField('gitiles_commit')
  c = common_pb2.GitilesCommit(
        host='chromium.googlesource.com',
        project='infra/infra',
        ref='refs/heads/main',
        id='a' * 40,
        position=42,
  )
  api.buildbucket.set_output_gitiles_commit(c)
  assert api.buildbucket.build.output.gitiles_commit == c

  api.step(
      'builder_url', cmd=None).presentation.step_text = (
          api.buildbucket.builder_url())

  api.step(
      'build_url', cmd=None).presentation.step_text = (
          api.buildbucket.build_url())

  api.step('builder_cache', cmd=None).presentation.step_text = (
      str(api.buildbucket.builder_cache_path)
  )


def GenTests(api):
  yield api.test(
      'basic-try',
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://chrome-internal.googlesource.com/a/repo.git',
          revision='a' * 40,
          build_number=123),
      api.buildbucket.simulated_get(build_pb2.Build(id=8922054662172514000))
  )

  yield api.test(
      'basic-ci-win',
      api.platform('win', 32),
      api.buildbucket.ci_build(
          project='proj-internal',
          bucket='ci',
          builder='ci-builder',
          git_repo='https://chrome-internal.googlesource.com/a/repo.git',
          build_number=0,
          tags=api.buildbucket.tags(user_agent=['cq', 'recipe']),
          exe=api.buildbucket.exe(cipd_pkg='path/to/cipd/pkg')),
      api.buildbucket.simulated_get(build_pb2.Build(id=8922054662172514000)),
  )

  yield api.test(
      'basic-try-bad-get',
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://chrome-internal.googlesource.com/a/repo.git',
          revision='a' * 40,
          build_number=123),
      api.step_data('buildbucket.get', api.json.output_stream({
        'responses': [{'error': {'code': 7}}],
      }, retcode=1)),
      api.post_process(DropExpectation),
      status = 'INFRA_FAILURE',
  )

  yield api.test(
      'basic-generic',
      api.buildbucket.generic_build(
          project='project',
          bucket='cron',
          builder='cron-builder'),
      api.post_process(DropExpectation),
  )

  yield api.test('no_properties')

  yield api.test(
      'cancel_step',
      api.runtime.global_shutdown_on_step('buildbucket.get', 'before'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://chrome-internal.googlesource.com/a/repo.git',
          revision='a' * 40,
          build_number=123,
          experiments=['luci.buildbucket.parent_tracking']
      ),
      api.properties(swarming_parent_run_id='1234'),
      status='CANCELED',
  )
