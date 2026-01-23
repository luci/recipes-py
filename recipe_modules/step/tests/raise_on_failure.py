# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.step.tests import raise_on_failure as raise_on_failure_pb
from recipe_engine import recipe_test_api, post_process

DEPS = [
    'properties',
    'step',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  bool infra_step = 1;
  bool set_status_to_exception = 2;
}
"""

PROPERTIES = raise_on_failure_pb.InputProperties

def RunSteps(api, props: raise_on_failure_pb.InputProperties):
  def failure_step_test_data():
    test_data = recipe_test_api.StepTestData()
    test_data.retcode = 1
    return test_data

  result = api.step(
      'non-raising step',
      ['bash', '-c', 'exit 1'],
      infra_step=props.infra_step,
      raise_on_failure=False,
      step_test_data=failure_step_test_data)

  status = None
  if props.set_status_to_exception:
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
      api.properties(raise_on_failure_pb.InputProperties(infra_step=True)),
      api.post_process(post_process.MustRun, 'in-between step'),
      api.post_process(post_process.StepException, 'non-raising step'),
      api.post_process(post_process.StatusException),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  yield api.test(
      'changed-status',
      api.properties(raise_on_failure_pb.InputProperties(set_status_to_exception=True)),
      api.post_process(post_process.MustRun, 'in-between step'),
      api.post_process(post_process.StepException, 'non-raising step'),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
