# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Simple recipe which sleeps in a subprocess forever to facilitate early
termination tests."""

DEPS = [
  'futures',
  'properties',
  'step',
]

from recipe_engine.post_process import DropExpectation

from PB.recipes.recipe_engine.engine_tests import long_sleep

PROPERTIES = long_sleep.InputProperties


def RunSteps(api, props):
  def _inner():
    try:
      api.step('sleep a bit', ['sleep', '360'], timeout=3)
    except api.step.StepFailure as ex:
      assert ex.had_timeout

  fut = api.futures.spawn_immediate(_inner)
  try:

    try:
      api.step('sleep forever', ['sleep', '360'])
    except api.step.StepFailure as ex:
      assert ex.was_cancelled
      if not props.recover:
        raise
  finally:
    fut.exception()

def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('sleep a bit', times_out_after=10),
      api.step_data('sleep forever', cancel=True),
      api.post_process(DropExpectation),
  )
  yield api.test(
      'recover',
      api.properties(recover=True),
      api.step_data('sleep a bit', times_out_after=10),
      api.step_data('sleep forever', cancel=True),
      api.post_process(DropExpectation),
  )


