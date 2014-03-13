# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections

from slave import recipe_api

class StepHistoryApi(recipe_api.RecipeApi, collections.Mapping):
  """
  Provide an OrderedDict-like view into the steps that have run, and what
  data they've returned.

  Each entry in step_history is an object() which has the attributes:
    * retcode
    * <module_name>.<module_specific_data>
  """
  def __getitem__(self, key):
    # NOTE: Ideally, we could constify the values here. However, APIs are
    # allowed to add any arbitrary data to step history items, so this would
    # be essentially impossible without significant additional code.
    return self._engine.step_history[key]

  def __iter__(self):  # pragma: no cover
    return iter(self._engine.step_history)

  def __len__(self):  # pragma: no cover
    return len(self._engine.step_history)

  @property
  def failed(self):
    """Return status of the build so far, as a bool."""
    return self._engine.step_history.failed

  def last_step(self):
    """Return the last StepData object, or None if no steps have run."""
    key = next(reversed(self._engine.step_history), None)
    return self[key] if key else None
