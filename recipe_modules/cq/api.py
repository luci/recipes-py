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
