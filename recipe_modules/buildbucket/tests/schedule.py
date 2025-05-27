# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import json_format
from google.protobuf import struct_pb2

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
  as_shadow = api.properties.get('as_shadow', False)
  child_bucket = api.properties.get('child_bucket', api.buildbucket.INHERIT)
  led_inherit_parent = api.properties.get('led_inherit_parent', False)
  # This is needed to provide coverage for the tags() method in api.py.
  tags = api.buildbucket.tags(**tags) if tags else tags
  req = api.buildbucket.schedule_request(
      bucket=child_bucket,
      tags=tags,
      as_shadow_if_parent_is_led=as_shadow,
      led_inherit_parent=led_inherit_parent,
      **req_body)

  include_sub_invs = api.properties.get('include_sub_invs', False)
  api.buildbucket.schedule([req], include_sub_invs=include_sub_invs)

  api.buildbucket.run(
      [req],
      raise_if_unsuccessful=api.properties.get('raise_failed_status'),
      timeout=5000,
  )

  api.buildbucket.run([], step_name='run nothing')


def GenTests(api):

  def test(test_name,
           response=None,
           tags=None,
           shadowed_bucket=None,
           on_backend=False,
           **req):
    req.setdefault('builder', 'linux')
    if shadowed_bucket:
      props_dict = {
          '$recipe_engine/led': {
              'shadowed_bucket': shadowed_bucket,
          },
      }
      properties = json_format.Parse(
          api.json.dumps(props_dict), struct_pb2.Struct())
    else:
      properties = None
    return (api.test(test_name) + api.runtime(is_experimental=False) +
            api.buildbucket.try_build(
                project='chromium',
                builder='Builder',
                git_repo='https://chromium.googlesource.com/chromium/src',
                revision='a' * 40,
                tags=api.buildbucket.tags(buildset='bs', unrelated='a'),
                exe=api.buildbucket.exe(
                    cipd_pkg='path/to/cipd/pkg',
                    cipd_ver='default_ver',
                    cmd=['luciexe'],
                ),
                properties=properties,
                on_backend=on_backend,
                backend_target="swarming://chromium-swarm") +
            api.properties(request_kwargs=req, tags=tags, response=response))

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

  yield test(test_name='backend', on_backend=True)

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
      api.buildbucket.simulated_schedule_output(err_batch_res) +
      api.expect_status('INFRA_FAILURE')
  )
  yield (
      test(test_name='mirror_failure') +
      api.properties(raise_failed_status=True) +
      api.buildbucket.simulated_collect_output([
        api.buildbucket.ci_build_message(
            build_id=8922054662172514001, status='FAILURE'),
      ], step_name='buildbucket.run.collect') +
      api.expect_status('INFRA_FAILURE')
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
          post_process.SummaryMarkdownRE,
          r'Buildbucket Internal Error'
      ) +
      api.post_process(post_process.DropExpectation) +
      api.expect_status('INFRA_FAILURE')
  )

  res_with_rdb = builds_service_pb2.BatchResponse(
      responses=[
          dict(
              schedule_build=dict(
                  infra=dict(
                      resultdb=dict(
                          invocation=str('invocations/build-87654321')
                      ),
                  ),
              ),
          ),
      ],
  )
  yield (
      test(test_name="include_sub_invocations") +
      api.properties(include_sub_invs=True) +
      api.buildbucket.simulated_schedule_output(res_with_rdb) +
      api.post_process(post_process.StepSuccess,
                       'include sub resultdb invocations')+
      api.post_process(post_process.DropExpectation)
  )

  yield (test(
      test_name="if not sub invocation then marked export root in ResultDB") +
         api.properties(include_sub_invs=False) +
         api.post_process(post_process.LogContains, 'buildbucket.schedule',
                          'request', ['"isExportRootOverride": true']))

  yield (test(
      test_name="schedule regular child for led by default",
      shadowed_bucket='original') + api.properties() +
         api.post_process(post_process.LogDoesNotContain,
                          'buildbucket.schedule', 'request', ['original']) +
         api.post_process(post_process.DropExpectation))

  yield (test(
      test_name="schedule shadow child for led", shadowed_bucket='original') +
         api.properties(as_shadow=True) +
         api.post_process(post_process.LogContains, 'buildbucket.schedule',
                          'request', ['original']) +
         api.post_process(post_process.DropExpectation))

  yield (test(test_name="not schedule shadow build for prod build") +
         api.properties(as_shadow=True) +
         api.post_process(post_process.LogDoesNotContain,
                          'buildbucket.schedule', 'request', ['original']) +
         api.post_process(post_process.DropExpectation))

  # It is in fact inheriting the parent's bucket.
  yield (test(
      test_name="schedule shadow child for led if provided bucket is parent's bucket",
      shadowed_bucket='original') + api.properties(as_shadow=True) +
         api.properties(child_bucket='original') +
         api.post_process(post_process.LogContains, 'buildbucket.schedule',
                          'request', ['original']) +
         api.post_process(post_process.LogDoesNotContain,
                          'buildbucket.schedule', 'request',
                          ['inheritFromParent']) +
         api.post_process(post_process.DropExpectation))

  yield (test(
      test_name="not schedule shadow child for led if provided bucket is not parent's bucket",
      shadowed_bucket='original') + api.properties(as_shadow=True) +
         api.properties(child_bucket='special') +
         api.post_process(post_process.LogContains, 'buildbucket.schedule',
                          'request', ['special']) +
         api.post_process(post_process.LogDoesNotContain,
                          'buildbucket.schedule', 'request', ['original']) +
         api.post_process(post_process.DropExpectation))

  yield (test(
      test_name="schedule shadow child for led inherit parent",
      shadowed_bucket='original') +
         api.properties(as_shadow=True, led_inherit_parent=True) +
         api.properties(child_bucket='original') + api.post_process(
             post_process.LogContains, 'buildbucket.schedule', 'request',
             ['original', '"inheritFromParent": true']) +
         api.post_process(post_process.DropExpectation))
