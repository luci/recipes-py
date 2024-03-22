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

  def legacy(self):  # pragma: no cover
    """DEPRECATED: Returns a set of properties, possibly used by legacy
    scripts.

    This excludes any recipe module-specific properties (i.e. those beginning
    with `$`).

    Instead of passing all of the properties as a blob, please consider passing
    specific arguments to scripts that need them. Doing this makes it much
    easier to debug and diagnose which scripts use which properties.
    """

    # Add all properties to this blacklist that are required for testing, but
    # not used by any lecacy scripts, in order to avoid vast expecation
    # changes.
    blacklist = set([
      'buildbotURL',
    ])
    props = {k: v for k, v in self.items()
             if k not in blacklist and not k.startswith('$')}
    if props.get('bot_id') and not props.get('slavename'):
      props['slavename'] = props['bot_id']
    return props

  def thaw(self):
    """Returns a read-write copy of all of the properties."""
    return self.properties_client.get_properties()
