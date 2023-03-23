# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime

from recipe_engine.post_process import StepSuccess, DoesNotRun, DropExpectation
from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    'runtime',
    'step',
    'time',
    'properties',
]


class TestClass:

  def __init__(self, api):
    self.m = api

  @exponential_retry(5, datetime.timedelta(seconds=1))
  def myFunction(self):
    self.m.step("step inside class method", None)
    raise Exception()


@exponential_retry(5, datetime.timedelta(seconds=1))
def helper_fn_that_needs_retries(api):
  api.step("helper step", None)
  raise Exception()


def RunSteps(api):
  now = api.time.time()
  api.time.sleep(5, with_step=True)
  api.step('echo', ['echo', str(now)])
  assert isinstance(api.time.utcnow(), datetime.datetime)
  assert isinstance(api.time.ms_since_epoch(), int)

  if api.properties.get('use_exponential_retry_from_api'):
    # Delay doesn't matter since this is a test.
    @api.time.exponential_retry(5, datetime.timedelta(seconds=1))
    def test_retries():
      api.step('running', None)
      raise Exception()

    try:
      test_retries()
    except:
      pass

  if api.properties.get("use_exponential_retry_from_import_on_class_method"):
    t = TestClass(api)
    try:
      t.myFunction()
    except:
      pass

  if api.properties.get("use_exponential_retry_from_import_on_helper_fn"):
    try:
      helper_fn_that_needs_retries(api)
    except:
      pass

  if api.properties.get(
      "use_exponential_retry_from_import_on_helper_fn_no_api"):
    try:
      helper_fn_that_needs_retries("")
    except:
      raise


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
      'exponential_retry_from_api',
      api.properties(use_exponential_retry_from_api=True),
      api.post_process(StepSuccess, 'running'),
      api.post_process(StepSuccess, 'running (2)'),
      api.post_process(StepSuccess, 'running (3)'),
      api.post_process(StepSuccess, 'running (4)'),
      api.post_process(StepSuccess, 'running (5)'),
      api.post_process(StepSuccess, 'running (6)'),
      api.post_process(DoesNotRun, 'running (7)'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'exponential_retry_from_import_on_class_method',
      api.properties(use_exponential_retry_from_import_on_class_method=True),
      api.post_process(StepSuccess, 'step inside class method'),
      api.post_process(StepSuccess, 'step inside class method (2)'),
      api.post_process(StepSuccess, 'step inside class method (3)'),
      api.post_process(StepSuccess, 'step inside class method (4)'),
      api.post_process(StepSuccess, 'step inside class method (5)'),
      api.post_process(StepSuccess, 'step inside class method (6)'),
      api.post_process(DoesNotRun, 'step inside class method (7)'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'exponential_retry_from_import_on_helper_fn',
      api.properties(use_exponential_retry_from_import_on_helper_fn=True),
      api.post_process(StepSuccess, 'helper step'),
      api.post_process(StepSuccess, 'helper step (2)'),
      api.post_process(StepSuccess, 'helper step (3)'),
      api.post_process(StepSuccess, 'helper step (4)'),
      api.post_process(StepSuccess, 'helper step (5)'),
      api.post_process(StepSuccess, 'helper step (6)'),
      api.post_process(DoesNotRun, 'helper step (7)'),
      api.post_process(DropExpectation),
  )

  yield api.test(
      'exponential_retry_from_import_on_helper_fn_no_api',
      api.properties(
          use_exponential_retry_from_import_on_helper_fn_no_api=True),
      api.expect_exception("AttributeError"))
