# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from infra.libs.infra_types import freeze, thaw
from slave import recipe_api
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
  def __init__(self, **kwargs):
    super(PropertiesApi, self).__init__(**kwargs)
    self._properties = freeze(self._engine.properties)

  def __getitem__(self, key):
    return self._properties[key]

  def __len__(self):
    return len(self._properties)

  def __iter__(self):
    return iter(self._properties)

  def legacy(self):
    """Returns a reduced set of properties, possibly used by legacy scripts."""

    # Add all properties to this blacklist that are required for testing, but
    # not used by any lecacy scripts, in order to avoid vast expecation
    # changes.
    blacklist = set([
      'buildbotURL',
    ])
    return {k: v for k, v in self.iteritems() if k not in blacklist}

  def thaw(self):
    """Returns a vanilla python jsonish dictionary of properties."""

    return thaw(self._engine.properties)
