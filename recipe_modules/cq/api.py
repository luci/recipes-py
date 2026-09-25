# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Wrapper for CV API."""

from __future__ import annotations

from typing import Any
from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb

from RECIPE_MODULES.recipe_engine import cq

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

  m: cq.DEPS

  def __init__(
      self, props: cq_pb.Input, *args: Any, **kwargs: Any
  ) -> None:
    super().__init__(*args, **kwargs)
    self._input = props

  def initialize(self) -> None:
    """Apply non-default value cq module properties to the cv module."""
    for name in _INPUT_PROPERTY_KEYS:
      value = getattr(self._input, name)
      if value:
        setattr(self.m.cv._input, name, value)
    self.m.cv.initialize()

  def __getattr__(self, name: str) -> Any:
    self.m.warning.issue('CQ_MODULE_DEPRECATED')
    return getattr(self.m.cv, name)
