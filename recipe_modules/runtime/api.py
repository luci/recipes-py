# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_api

from recipe_engine.internal.global_shutdown import GLOBAL_SHUTDOWN


class RuntimeApi(recipe_api.RecipeApi):
  """This module assists in experimenting with production recipes.

  For example, when migrating builders from Buildbot to pure LUCI stack.
  """

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._properties = properties

  @property
  def is_experimental(self):
    """True if this recipe is currently running in experimental mode.

    Typical usage is to modify steps which produce external side-effects so that
    non-production runs of the recipe do not affect production data.

    Examples:
      * Uploading to an alternate google storage file name when in non-prod mode
      * Appending a 'non-production' tag to external RPCs
    """
    return self._properties.is_experimental

  @property
  def in_global_shutdown(self):
    """True iff this recipe is currently in the 'grace_period' specified by
    `LUCI_CONTEXT['deadline']`.

    This can occur when:
      * The LUCI_CONTEXT has hit the 'soft_deadline'; OR
      * The LUCI_CONTEXT has been 'canceled' and the recipe_engine has received
        a SIGTERM (on *nix) or Ctrl-Break (on Windows).

    As of 2021Q2, while the recipe is in the grace_period, it can do anything
    _except_ for starting new steps (but it can e.g. update presentation of open
    steps, or return RawResult from RunSteps). Attempting to start a step while
    in the grace_period will cause the step to skip execution. When a signal is
    received or the soft_deadline is hit, all currently running steps will be
    signaled in turn (according to the `LUCI_CONTEXT['deadline']` protocol).

    It is good practice to ensure that recipes exit cleanly when canceled or
    time out, and this could be used anywhere to skip 'cleanup' behavior in
    'finally' clauses or context managers.

    https://chromium.googlesource.com/infra/luci/luci-py/+/HEAD/client/LUCI_CONTEXT.md
    """
    return GLOBAL_SHUTDOWN.ready()
