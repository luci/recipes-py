# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Launches the repo bundler."""

DEPS = [
    'python',
    'step',
]


def RunSteps(api):
  api.python.succeeding_step("success", ["This step is a success"],
                             as_log='success')

  # Test that a failing step raises StepFailure.
  was_failure = False
  try:
    api.python.failing_step("failure", "This step is a failure :(")
  except api.step.StepFailure:
    was_failure = True
  assert was_failure


def GenTests(api):
  yield api.test('basic')
