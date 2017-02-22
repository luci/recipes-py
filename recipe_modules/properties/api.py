# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine.types import freeze
import collections

# Use RecipeApiPlain because collections.Mapping has its own metaclass.
# Additionally, nothing in this class is a composite_step (nothing in this class
# is any sort of step :).
class PropertiesApi(recipe_api.RecipeApiPlain, collections.Mapping):
  """
  Provide an immutable mapping view into the 'properties' for the current run.

  The value of this api is equivalent to this transformation of the legacy
  build values:
    val = factory_properties
    val.update(build_properties)
  """

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
    """Returns a set of properties, possibly used by legacy scripts."""

    # Add all properties to this blacklist that are required for testing, but
    # not used by any lecacy scripts, in order to avoid vast expecation
    # changes.
    blacklist = set([
      'buildbotURL',
    ])
    props = {k: v for k, v in self.iteritems() if k not in blacklist}
    if props.get('bot_id') and not props.get('slavename'):
      props['slavename'] = props['bot_id']
    return props

  def thaw(self):
    """Returns a vanilla python jsonish dictionary of properties."""
    return self.properties_client.get_properties()
