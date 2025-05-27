# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_test_api


class RuntimeTestApi(recipe_test_api.RecipeTestApi):

  def __call__(self, is_experimental=False):
    """Simulate runtime state of a build."""
    assert isinstance(is_experimental, bool), '%r (%s)' % (
        is_experimental, type(is_experimental))
    ret = self.test(None)
    ret.properties = {
      '$recipe_engine/runtime': {
        'is_experimental': is_experimental,
      },
    }
    return ret

  def global_shutdown_on_step(self, step_name, event='after'):
    """Simulates an incoming SIGTERM/Ctrl-Break to the recipe execution.

    When the test is 'canceled', it behaves as if the real recipe received
    an external cancellation request (or hit the global 'soft_deadline' from
    LUCI_CONTEXT['deadline']). In this state, `runtime.in_global_shutdown`
    will be True, and new steps will be skipped.

    If set for multiple steps, only applies on the first step run (other
    steps with this set will be no-op).

    Args:
      * step_name - The name of the step to cancel before or after.
      * event - Simulate cancellation 'after' or 'before' the indicated
        step. If 'before', the test will set shutdown immediately before
        `step_name` (meaning that `step_name` will not run).
    """
    assert event in ('before', 'after'), 'bad shutdown_on_step event'
    return self.step_data(step_name, global_shutdown_event = event)
