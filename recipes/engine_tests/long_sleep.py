# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Simple recipe which sleeps in a subprocess forever to facilitate early
termination tests."""

from __future__ import annotations

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
      api.step('sleep a bit', ['sleep', '360'], timeout=5)
    except api.step.StepFailure as ex:
      assert ex.had_timeout

  fut = api.futures.spawn_immediate(_inner)
  try:

    try:
      api.step('sleep forever', ['sleep', '360'])
    except api.step.StepFailure as ex:
      assert ex.was_cancelled
      if props.HasField('check_retcode'):
        check_retcode = props.check_retcode
        expected = (
            check_retcode.retcode
            if check_retcode.HasField('retcode') else None)
        assert ex.retcode == expected, f'expected {expected}, got {ex.retcode}'
      if not props.recover:
        raise
  finally:
    fut.exception()

def GenTests(api):
  yield api.test(
      'basic',
      api.properties(check_retcode={}),
      api.step_data('sleep a bit', times_out_after=10),
      api.step_data('sleep forever', cancel=True),
      api.post_process(DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'recover',
      api.properties(recover=True, check_retcode={'retcode': 1}),
      api.step_data('sleep a bit', times_out_after=10),
      api.step_data('sleep forever', cancel=True, retcode=1),
      api.post_process(DropExpectation),
  )
