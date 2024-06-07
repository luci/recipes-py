# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides access to the recipes input properties.

Every recipe is run with a JSON object called "properties". These contain all
inputs to the recipe. Some common examples would be properties like "revision",
which the build scheduler sets to tell a recipe to build/test a certain
revision.

The properties that affect a particular recipe are defined by the recipe itself,
and this module provides access to them.

Recipe properties are read-only; the values obtained via this API reflect the
values provided to the recipe engine at the beginning of execution. There is
intentionally no API to write property values (lest they become a kind of
random-access global variable).
"""

import collections.abc

from recipe_engine import recipe_api
from recipe_engine.engine_types import freeze


class PropertiesApi(recipe_api.RecipeApi, collections.abc.Mapping):
  """PropertiesApi implements all the standard Mapping functions, so you
  can use it like a read-only dict."""

  properties_client = recipe_api.RequireClient('properties')

  def __init__(self, **kwargs):
    super(PropertiesApi, self).__init__(**kwargs)
    self._frozen_properties = None

  @property
  def _properties(self):
    if self._frozen_properties is None:
      self._frozen_properties = freeze(
          self.properties_client.get_properties())
    return self._frozen_properties

  def __getitem__(self, key):
    return self._properties[key]

  def __len__(self):
    return len(self._properties)

  def __iter__(self):
    return iter(self._properties)

  def thaw(self):
    """Returns a read-write copy of all of the properties."""
    return self.properties_client.get_properties()
