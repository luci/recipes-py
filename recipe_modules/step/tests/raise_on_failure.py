# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api, recipe_test_api, post_process

DEPS = [
    'properties',
    'step',
]

PROPERTIES = {
  'infra_step': recipe_api.Property(default=False),
  'set_status_to_exception': recipe_api.Property(default=False),
}

def RunSteps(api, infra_step, set_status_to_exception):
  def failure_step_test_data():
    test_data = recipe_test_api.StepTestData()
    test_data.retcode = 1
    return test_data

  result = api.step(
      'non-raising step',
      ['bash', '-c', 'exit 1'],
      infra_step=infra_step,
      raise_on_failure=False,
      step_test_data=failure_step_test_data)

  status = None
  if set_status_to_exception:
    status = result.presentation.status
    result.presentation.status = api.step.EXCEPTION

  api.step('in-between step', [])

  api.step.raise_on_failure(result, status_override=status)

def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.MustRun, 'in-between step'),
      api.post_process(post_process.StepFailure, 'non-raising step'),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'infra-step',
      api.properties(infra_step=True),
      api.post_process(post_process.MustRun, 'in-between step'),
      api.post_process(post_process.StepException, 'non-raising step'),
      api.post_process(post_process.StatusException),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'changed-status',
      api.properties(set_status_to_exception=True),
      api.post_process(post_process.MustRun, 'in-between step'),
      api.post_process(post_process.StepException, 'non-raising step'),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
