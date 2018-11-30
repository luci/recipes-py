# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests for api.python.infra_failing_step."""

from recipe_engine import post_process

DEPS = [
  'python',
  'step',
]


def RunSteps(api):
  try:
    api.python.infra_failing_step(
        'infra failure',
        ['This step is an infra failure!'])
  except api.step.InfraFailure:
    api.python.succeeding_step(
        'InfraFailure',
        ['Expected exception thrown.'])
  except api.step.StepFailure:  # pragma: no cover
    api.python.failing_step(
        'StepFailure',
        ['Unexpected exception thrown.'])
  else:  # pragma: no cover
    api.python.failing_step(
        'No failure',
        ['No exception thrown?'])


def GenTests(api):
  yield (
      api.test('basic') +
      api.post_process(post_process.MustRun, 'InfraFailure') +
      api.post_process(post_process.StatusSuccess) +
      api.post_process(post_process.DropExpectation))
