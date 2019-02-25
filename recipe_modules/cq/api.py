# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
from enum import Enum

from recipe_engine import recipe_api


class CQApi(recipe_api.RecipeApi):
  """This module provides recipe API of LUCI CQ, aka pre-commit testing system.

  More information about CQ:
    https://chromium.googlesource.com/infra/luci/luci-go/+/master/cq
  """

  class State(Enum):
    INACTIVE = 0
    DRY = 1
    FULL = 2

  # Re-bind constants for easier usage of CQApi:
  # >>> if api.cq.state == api.cq.DRY:
  INACTIVE = State.INACTIVE
  DRY = State.DRY
  FULL = State.FULL

  def __init__(self, properties, **kwargs):
    super(CQApi, self).__init__(**kwargs)
    self._properties = properties
    self._state = None
    self._triggered_build_ids = []

  def initialize(self):
    v = self._properties.get('dry_run')
    if v is None:
      self._state = self.INACTIVE
    elif v:
      self._state = self.DRY
    else:
      self._state = self.FULL

  @property
  def state(self):
    """CQ state pertaining to this recipe execution."""
    return self._state

  @property
  def triggered_build_ids(self):
    """Returns recorded build ids as a list of integers."""
    return self._triggered_build_ids

  def record_triggered_builds(self, *builds):
    """Adds given Buildbucket builds to the list of triggered builds for CQ
    to wait on corresponding build completion later.

    Must be called after some step.

    Expected usage:
      ```python
        api.cq.record_triggered_builds(*api.buildbucket.schedule([req1, req2]))
      ```

    Args:
      * [`Build`](https://chromium.googlesource.com/infra/luci/luci-go/+/master/buildbucket/proto/build.proto)
        objects, typically returned by `api.buildbucket.schedule`.
    """
    return self.record_triggered_build_ids(*[b.id for b in builds])

  def record_triggered_build_ids(self, *build_ids):
    """Adds given Buildbucket build ids to the list of triggered builds for CQ
    to wait on corresponding build completion later.

    Must be called after some step.

    Args:
      * build_id (int or string): Buildbucket build id.
    """
    if not build_ids:
      return
    self._triggered_build_ids.extend(int(bid) for bid in build_ids)
    assert self.m.step.active_result, 'must be called after some step'
    self.m.step.active_result.presentation.properties['triggered_build_ids'] = [
          str(build_id) for build_id in self._triggered_build_ids]
