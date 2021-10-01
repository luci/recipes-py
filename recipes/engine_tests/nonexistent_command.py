# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'step',
]


def RunSteps(api):
  try:
    api.step('normal step', ['missing_cmd0'])
  except:
    step_text = api.step.active_result.presentation.step_text
    assert step_text == "cmd0 'missing_cmd0' not found", step_text
  else:
    assert False, 'step must fail due to cmd0 not found'

  try:
    api.step.sub_build('merge step', ['missing_luciexe'], build_pb2.Build())
  except:
    step_text = api.step.active_result.presentation.step_text
    assert step_text == "cmd0 'missing_luciexe' not found", step_text
  else:
    assert False, 'step must fail due to cmd0 not found'


def GenTests(_api):
  # step_runner for simulation test will always resolve cmd0 because its lack
  # of filesystem support. This test will be executed using prod step_runner
  # in //unittests/run_test.py.
  # TODO(yiwzhang): use `yield from ()` after python2 support is fully dropped.
  return
  yield
