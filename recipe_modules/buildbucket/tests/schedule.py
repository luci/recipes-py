# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import engine_types
from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2

DEPS = [
  'buildbucket',
  'json',
  'properties',
  'runtime',
  'step',
]


def RunSteps(api):
  # Convert from FrozenDict
  req_body = engine_types.thaw(api.properties.get('request_kwargs'))
  tags = api.properties.get('tags')
  # This is needed to provide coverage for the tags() method in api.py.
  tags = api.buildbucket.tags(**tags) if tags else tags
  req = api.buildbucket.schedule_request(tags=tags, **req_body)
  api.buildbucket.schedule([req])

  api.buildbucket.run(
      [req],
      raise_if_unsuccessful=api.properties.get('raise_failed_status'),
      timeout=5000,
  )

  api.buildbucket.run([], step_name='run nothing')


def GenTests(api):

  def test(test_name, response=None, tags=None, **req):
    req.setdefault('builder', 'linux')
    return (
      api.test(test_name) +
      api.runtime(is_experimental=False) +
      api.buildbucket.try_build(
          project='chromium',
          builder='Builder',
          git_repo='https://chromium.googlesource.com/chromium/src',
          revision='a' * 40,
          tags=api.buildbucket.tags(buildset='bs', unrelated='a'),
      ) +
      api.properties(request_kwargs=req, tags=tags, response=response)
    )

  yield test('basic')

  yield test('exe_cipd_version', exe_cipd_version='some_ver')

  yield test(
      test_name='tags',
      tags={'a': 'b'}
  )

  yield test(
      test_name='dimensions',
      dimensions=[{'key': 'os', 'value': 'Windows'}]
  )

  yield test(
      test_name='critical',
      critical=True,
  )

  yield test(
      test_name='properties',
      properties={
          'str': 'b',
          'obj': {
              'p': 1,
          },
      }
  )

  yield test(
      test_name='experimental',
      experimental=common_pb2.YES,
  )

  yield test(
      test_name='non-experimental',
      experimental=common_pb2.NO,
  )

  yield test(
      test_name='experiments',
      experiments={
          'luci.exp_foo': True,
          'luci.exp_bar': False,
      },
  )

  err_batch_res = builds_service_pb2.BatchResponse(
      responses=[
        dict(
            error=dict(
                code=1,
                message='bad',
            ),
        ),
      ],
  )
  yield (
      test(test_name='error') +
      api.buildbucket.simulated_schedule_output(err_batch_res)
  )
  yield (
      test(test_name='mirror_failure') +
      api.properties(raise_failed_status=True) +
      api.buildbucket.simulated_collect_output([
        api.buildbucket.ci_build_message(
            build_id=8922054662172514001, status='FAILURE'),
      ], step_name='buildbucket.run.collect')
  )

  yield (
      test(test_name='infra_error') +
      api.override_step_data(
          'buildbucket.schedule',
          api.json.invalid(None),
          retcode=1
      ) +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.ResultReasonRE,
          r'Buildbucket Internal Error'
      ) +
      api.post_process(post_process.DropExpectation)
  )
