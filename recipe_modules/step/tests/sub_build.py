# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.config_types import Path

from google.protobuf import json_format as jsonpb
from google.protobuf import timestamp_pb2

from PB.recipe_modules.recipe_engine.step.tests import (
  properties as properties_pb2
)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import step as step_pb2

DEPS = [
  'assertions',
  'context',
  'json',
  'path',
  'properties',
  'step',
]

PROPERTIES = properties_pb2.SubBuildInputProps

def RunSteps(api, props):
  output_path = None
  if props.HasField('output_path'):
    output_path = (
      getattr(api.path, props.output_path.base) / props.output_path.file)
  with api.context(infra_steps=props.infra_step):
    input_build = props.input_build if props.HasField('input_build') else (
        build_pb2.Build(id=11111, status=common_pb2.SCHEDULED))
    ret = api.step.sub_build(
      'launch sub build',
      ['luciexe', '--foo', 'bar', '--json-summary', api.json.output()],
      input_build,
      output_path=output_path,
      legacy_global_namespace=props.legacy,
      merge_output_properties_to=['a', 'b'],
      step_test_data= lambda: (
        api.json.test_api.output('{"hello": "world"}') +
        api.step.test_api.sub_build(
          build_pb2.Build(id=11111, status=common_pb2.SUCCESS))
      ),
    )

  api.assertions.assertIsNotNone(ret.step.sub_build)
  if props.HasField('expected_sub_build'):
    api.assertions.assertEqual(ret.step.sub_build, props.expected_sub_build)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(properties_pb2.SubBuildInputProps(
          expected_sub_build=build_pb2.Build(
              id=11111, status=common_pb2.SUCCESS),
      )),
  )

  yield api.test(
      'legacy',
      api.properties(properties_pb2.SubBuildInputProps(
          expected_sub_build=build_pb2.Build(
              id=11111, status=common_pb2.SUCCESS),
          legacy=True,
      )),
  )

  yield api.test(
      'output',
      api.properties(properties_pb2.SubBuildInputProps(
          output_path=properties_pb2.SubBuildInputProps.Path(
              base='start_dir',
              file='sub_build.json'),
          expected_sub_build=build_pb2.Build(
              id=45678, status=common_pb2.SUCCESS),
      )),
      api.step_data(
          'launch sub build',
          api.step.sub_build(
              build_pb2.Build(id=45678, status=common_pb2.SUCCESS))
      ),
  )

  yield api.test(
      'output_file_exists',
      api.properties(
          output_path=properties_pb2.SubBuildInputProps.Path(
              base='start_dir',
              file='sub_build.json'),
      ),
      api.path.exists(api.path.start_dir / 'sub_build.json'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdownRE,
          r'.*expected non-existent output path'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'invalid_extension',
      api.properties(properties_pb2.SubBuildInputProps(
          output_path=properties_pb2.SubBuildInputProps.Path(
              base='start_dir',
              file='sub_build.yaml'),
      )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdownRE,
          r'.*expected extension of output path to be one of'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'failure_status',
      api.step_data(
          'launch sub build',
          api.step.sub_build(
              build_pb2.Build(id=1, status=common_pb2.FAILURE)),
      ),
      api.post_process(post_process.StepFailure, 'launch sub build'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'infra_failure_status',
      api.step_data(
          'launch sub build', api.step.sub_build(
              build_pb2.Build(id=1, status=common_pb2.INFRA_FAILURE))
      ),
      api.post_process(post_process.StepException, 'launch sub build'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'infra_step',
      api.step_data(
          'launch sub build', api.step.sub_build(
              build_pb2.Build(id=1, status=common_pb2.FAILURE))
      ),
      api.properties(properties_pb2.SubBuildInputProps(infra_step=True)),
      api.post_process(post_process.StepException, 'launch sub build'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'output_summary_markdown',
      api.step_data(
          'launch sub build', api.step.sub_build(
              build_pb2.Build(
                  id=1, status=common_pb2.SUCCESS,
                  summary_markdown='This is the summary of sub build'))
      ),
      api.post_process(post_process.StepTextEquals, 'launch sub build',
                       'This is the summary of sub build'),
      api.post_process(post_process.DropExpectation),
  )

  build = build_pb2.Build(id=1234, status=common_pb2.SUCCESS)
  build.output.logs.extend([
    common_pb2.Log(
      name='cool',
      url='some/cool',
    ),
    common_pb2.Log(
      name='awesome',
      url='some/awesome',
    )
  ])
  yield api.test(
      'merge_output_logs',
      api.step_data('launch sub build', api.step.sub_build(build)),
  )

  yield api.test(
      'non_terminal_status',
      api.step_data(
          'launch sub build', api.step.sub_build(
              build_pb2.Build(id=1, status=common_pb2.STARTED))
      ),
      api.post_process(post_process.StepException, 'launch sub build'),
      api.post_process(
          post_process.StepTextEquals, 'launch sub build',
          'Merge Step Error: expected terminal build status of sub build; '
          'got status: STARTED.'),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'output_missing',
      api.step_data('launch sub build', api.step.sub_build(None)),
      api.post_process(post_process.StepException, 'launch sub build'),
      api.post_process(
          post_process.StepTextEquals, 'launch sub build',
          "Merge Step Error: Can't find the final build output for luciexe."),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  input_build=build_pb2.Build(
    id=88888,
    status=common_pb2.INFRA_FAILURE,
    status_details=common_pb2.StatusDetails(
        timeout=common_pb2.StatusDetails.Timeout()),
    create_time=timestamp_pb2.Timestamp(seconds=1598338800),
    start_time=timestamp_pb2.Timestamp(seconds=1598338801),
    end_time=timestamp_pb2.Timestamp(seconds=1598425200),
    update_time=timestamp_pb2.Timestamp(seconds=1598425200),
    summary_markdown='awesome summary',
    steps=[step_pb2.Step(name='first step'),],
    tags=[common_pb2.StringPair(key='foo', value='bar'),],
  )
  build.output.properties['some_key'] = 'some_value'
  build.output.logs.add(name='stdout')

  # TODO(yiwzhang): figure out a way to enable this check in py3. In
  # Python3, the raw bytes for stdin data is decoded to utf-8 string in
  # order to display the data in expectation file. Re-encode it will not
  # work because all non-valid utf-8 characters have been replaced with
  # replacement character.
  #
  # NOTE: When re-enabling, remove `nocover` comments in step/test_api.py.
  if False:  # pragma: no cover

    def check_luciexe_initial_build(check, steps):
      import sys
      if sys.version_info.major == 2:
        initial_build = build_pb2.Build()
        initial_build.ParseFromString(steps['launch sub build'].stdin)
        check(initial_build.id == 88888)
        check(initial_build.status == common_pb2.STARTED)
        check(initial_build.create_time.ToSeconds() == 1677836800)
        check(initial_build.start_time.ToSeconds() == 1677836801)
        check(initial_build.tags == input_build.tags)
        check(not initial_build.summary_markdown)
        check(not initial_build.HasField('status_details'))
        check(not initial_build.HasField('end_time'))
        check(not initial_build.HasField('update_time'))
        check(not initial_build.steps)
        check(not initial_build.HasField('output'))

    yield api.test(
        'clear_fields_of_input_build',
        api.properties(
            properties_pb2.SubBuildInputProps(input_build=input_build,)),
        api.step.initial_build_create_time(1677836800),
        api.step.initial_build_start_time(1677836801),
        api.post_check(check_luciexe_initial_build),
        api.post_process(post_process.DropExpectation),
    )
