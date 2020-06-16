# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.config_types import Path

from google.protobuf import json_format as jsonpb

from PB.recipe_modules.recipe_engine.step.tests import (
  properties as properties_pb2
)
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
  'assertions',
  'path',
  'properties',
  'step',
]

PROPERTIES = properties_pb2.SubBuildInputProps

def RunSteps(api, props):
  output_path = None
  if props.HasField('output_path'):
    output_path = (
      api.path[props.output_path.base].join(props.output_path.file))
  ret = api.step.sub_build(
    'launch sub build',
    ['luciexe', '--foo', 'bar'],
    build_pb2.Build(id=11111, status=common_pb2.SCHEDULED),
    output_path=output_path
  )

  api.assertions.assertIsNotNone(ret.step.sub_build)
  if props.HasField('expected_sub_build'):
    api.assertions.assertEqual(ret.step.sub_build, props.expected_sub_build)


def GenTests(api):
  yield (
    api.test('basic') +
    api.properties(properties_pb2.SubBuildInputProps(
      expected_sub_build=build_pb2.Build(id=12345, status=common_pb2.SUCCESS),
    )) +
    api.step_data('launch sub build', api.step.sub_build(
      build_pb2.Build(id=12345, status=common_pb2.SUCCESS))
    )
  )

  yield (
    api.test('output') +
    api.properties(properties_pb2.SubBuildInputProps(
      output_path=properties_pb2.SubBuildInputProps.Path(
        base='start_dir',
        file='sub_build.json'),
      expected_sub_build=build_pb2.Build(id=45678, status=common_pb2.SUCCESS),
    )) +
    api.step_data('launch sub build', api.step.sub_build(
      build_pb2.Build(id=45678, status=common_pb2.SUCCESS))
    )
  )

  yield (
    api.test('output_file_exists') +
    api.properties(
      output_path=properties_pb2.SubBuildInputProps.Path(
        base='start_dir',
        file='sub_build.json'),
    ) +
    api.path.exists(api.path['start_dir'].join('sub_build.json')) +
    api.expect_exception('ValueError') +
    api.post_process(
      post_process.ResultReasonRE,
      r'.*expected non-existent output path') +
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('invalid_extension') +
    api.properties(properties_pb2.SubBuildInputProps(
      output_path=properties_pb2.SubBuildInputProps.Path(
        base='start_dir',
        file='sub_build.yaml'),
    )) +
    api.expect_exception('ValueError') +
    api.post_process(
      post_process.ResultReasonRE,
      r'.*expected extension of output path to be one of') +
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('failure_status') +
    api.step_data('launch sub build', api.step.sub_build(
      build_pb2.Build(id=1, status=common_pb2.FAILURE))
    ) +
    # Step should succeed even though the sub build fails
    api.post_process(post_process.StepSuccess, 'launch sub build') +
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('non_terminal_status') +
    api.step_data('launch sub build', api.step.sub_build(
      build_pb2.Build(id=1, status=common_pb2.STARTED))
    ) +
    api.post_process(post_process.StepException, 'launch sub build') +
    api.post_process(post_process.StepTextEquals, 'launch sub build',
      'Merge Step Error: expected terminal build status of sub build; '
      'got status: STARTED.')+
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('output_missing') +
    api.step_data('launch sub build', api.step.sub_build(None)) +
    api.post_process(post_process.StepException, 'launch sub build') +
    api.post_process(post_process.StepTextEquals, 'launch sub build',
      "Merge Step Error: Can't find the final build output for luciexe.") +
    api.post_process(post_process.DropExpectation)
  )