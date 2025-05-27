# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'led',
  'step',
]

def RunSteps(api):
  try:
    api.led('get-builder', 'fake/bucket:no-exist')
    assert False, 'get-builder found a build'  # pragma: no cover
  except api.step.StepFailure:
    pass

  try:
    api.led('get-build', 123456789)
    assert False, 'get-build found a build'  # pragma: no cover
  except api.step.StepFailure:
    pass

  try:
    api.led('get-swarm', 'deadbeef')
    assert False, 'get-swarm found a build'  # pragma: no cover
  except api.step.StepFailure:
    pass


def GenTests(api):
  yield api.test(
      'find nothing',
      api.led.mock_get_builder(None, 'fake', 'bucket', 'no-exist'),
      api.led.mock_get_build(None, 123456789),
      api.led.mock_get_swarm(None, 'deadbeef'),
  )
