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
  except api.step.StepTimeout:
    api.step('caught timeout', [])
    raise


def GenTests(api):
  yield (
      api.test('timeout') +
      api.properties(timeout=1) +
      api.step_data('timeout', times_out_after=20)
    )
