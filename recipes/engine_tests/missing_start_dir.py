# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that deleting the current working directory doesn't immediately fail"""

from __future__ import annotations

DEPS = [
  'step',
  'path',
]


def RunSteps(api):
  api.step('innocent step', ['bash', '-c', "echo some step"])
  api.step('nuke it', ['rm', '-rf', api.path.start_dir])

  try:
    api.step('bash needs cwd', ['bash', '-c', "echo fail"])
    assert True
  except api.step.StepFailure:  # pragma: no cover
    assert False

  api.step('python does not', ['python3', '-c', 'print("hi")'])


def GenTests(api):
  yield api.test('basic')
