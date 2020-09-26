# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'legacy_annotation',
  'raw_io',
  'step',
]

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import step as step_pb2


def RunSteps(api):
  api.legacy_annotation('run annotation script',
    cmd=['python', '-u', api.resource('anno.py')],
    step_test_data=lambda: api.legacy_annotation.test_api.success_step,
  )


def GenTests(api):
  sub_build = build_pb2.Build(id=1, status=common_pb2.SUCCESS)
  sub_build.steps.add().CopyFrom(
    step_pb2.Step(name='Hi Sub Annotation', status=common_pb2.SUCCESS),
  )
  props = sub_build.output.properties
  props['str_prop'] = 'hello str'
  props.get_or_create_struct('obj_prop')['hello'] = 'dict'
  props.get_or_create_list('list_prop').extend(['hello', 'list'])
  yield (
    api.test('basic') +
    api.step_data('run annotation script', api.step.sub_build(sub_build))
  )

  yield (
    api.test('default step_test_data') +
    api.post_process(post_process.StepSuccess, 'run annotation script') +
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('failure') +
    api.step_data('run annotation script',
                  api.legacy_annotation.failure_step) +
    api.post_process(post_process.StepFailure, 'run annotation script') +
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('infra failure') +
    api.step_data('run annotation script',
                  api.legacy_annotation.infra_failure_step) +
    api.post_process(post_process.StepException, 'run annotation script') +
    api.post_process(post_process.DropExpectation)
  )

  yield (
    api.test('kitchen basic') +
    api.legacy_annotation.simulate_kitchen()
  )

  yield (
    api.test('kitchen failure') +
    api.legacy_annotation.simulate_kitchen() +
    api.step_data('run annotation script', retcode=1) +
    api.post_process(post_process.StepFailure, 'run annotation script') +
    api.post_process(post_process.DropExpectation)
  )