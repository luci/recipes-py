# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.step.tests import timeout as timeout_pb

DEPS = [
  'properties',
  'step',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  int32 timeout = 1;
}
"""

PROPERTIES = timeout_pb.InputProperties


def RunSteps(api, props: timeout_pb.InputProperties):
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
      api.properties(timeout_pb.InputProperties(timeout=1)) +
      api.step_data('timeout', times_out_after=20) +
      api.step_data('timeout (2)', times_out_after=20)
    )
