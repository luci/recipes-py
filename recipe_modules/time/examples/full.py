# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime

from recipe_engine.post_process import StepSuccess, DoesNotRun, DropExpectation

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    'runtime',
    'step',
    'time',
    'properties',
]


def RunSteps(api):
  now = api.time.time()
  api.time.sleep(5, with_step=True)
  api.step('echo', ['echo', str(now)])
  assert isinstance(api.time.utcnow(), datetime.datetime)
  assert isinstance(api.time.ms_since_epoch(), int)

  if not api.properties.get('number_of_retries'):
    return

  # Delay doesn't matter since this is a test.
  @api.time.exponential_retry(api.properties['number_of_retries'],
                              datetime.timedelta(seconds=1))
  def test_retries():
    api.step('running', None)
    raise Exception()

  try:
    test_retries()
  except:
    pass


def GenTests(api):
  yield api.test('defaults')

  yield api.test('seed_and_step') + api.time.seed(123) + api.time.step(2)

  yield api.test(
      'cancel_sleep',
      api.time.seed(123),
      api.time.step(2),
      api.runtime.global_shutdown_on_step('sleep 5', 'after'),
  )

  yield api.test(
      'exponential_retry',
      api.properties(number_of_retries=5),
      api.post_process(StepSuccess, 'running'),
      api.post_process(StepSuccess, 'running (2)'),
      api.post_process(StepSuccess, 'running (3)'),
      api.post_process(StepSuccess, 'running (4)'),
      api.post_process(StepSuccess, 'running (5)'),
      api.post_process(StepSuccess, 'running (6)'),
      api.post_process(DoesNotRun, 'running (7)'),
      api.post_process(DropExpectation),
  )
