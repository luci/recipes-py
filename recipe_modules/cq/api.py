# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Wrapper for CV API."""

from __future__ import annotations

from recipe_engine import recipe_api

_INPUT_PROPERTY_KEYS = (
    'active',
    'dry_run',
    'experimental',
    'top_level',
    'run_mode',
    'owner_is_googler',
)


class CQApi(recipe_api.RecipeApi):
  """This module is a thin wrapper of the cv module."""

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._input = props

  def initialize(self):
    """Apply non-default value cq module properties to the cv module."""
    for name in _INPUT_PROPERTY_KEYS:
      value = getattr(self._input, name)
      if value:
        setattr(self.m.cv._input, name, value)
    self.m.cv.initialize()

  def __getattr__(self, name):
    self.m.warning.issue('CQ_MODULE_DEPRECATED')
    return getattr(self.m.cv, name)
