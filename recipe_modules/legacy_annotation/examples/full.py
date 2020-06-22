# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'legacy_annotation',
  'raw_io',
  'step',
]

import textwrap

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import step as step_pb2


def RunSteps(api):
  api.legacy_annotation('run annotation script', cmd=[
      'python', '-u', api.resource('anno.py')])


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