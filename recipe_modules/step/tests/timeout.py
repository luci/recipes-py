# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api


DEPS = [
  'properties',
  'step',
]


PROPERTIES = {
  'timeout': recipe_api.Property(default=0, kind=int),
}


def RunSteps(api, timeout):
  # Timeout causes the recipe engine to raise an exception if your step takes
  # longer to run than you allow. Units are seconds.
  try:
    api.step('timeout', ['sleep', '20'], timeout=1)
  except api.step.StepFailure as ex:
    assert ex.had_timeout
    api.step('caught timeout (failure)', [])

  # If the step was marked as an infra_step, then it raises InfraFailure
  # on timeout.
  try:
    api.step('timeout', ['sleep', '20'], timeout=1, infra_step=True)
  except api.step.InfraFailure as ex:
    assert ex.had_timeout
    api.step('caught timeout (failure)', [])


def GenTests(api):
  yield (
      api.test('timeout') +
      api.properties(timeout=1) +
      api.step_data('timeout', times_out_after=20) +
      api.step_data('timeout (2)', times_out_after=20)
    )
