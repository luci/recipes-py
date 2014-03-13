# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api
import collections

class ImmutableMapping(dict):
  def __init__(self, data):
    super(ImmutableMapping, self).__init__(data)
    assert all(isinstance(v, collections.Hashable) for v in self.itervalues())
    self._hash_value = hash(tuple(sorted(self.iteritems())))

  def __setitem__(self, key, value):  # pragma: no cover
    raise TypeError("May not modify an ImmutableMapping")

  def __delitem__(self, key):  # pragma: no cover
    raise TypeError("May not modify an ImmutableMapping")

  def __hash__(self):
    return self._hash_value


def freeze(obj):
  if isinstance(obj, dict):
    return ImmutableMapping((k, freeze(v)) for k, v in obj.iteritems())
  elif isinstance(obj, list):
    return tuple(freeze(x) for x in obj)
  elif isinstance(obj, collections.Hashable):
    return obj
  else:  # pragma: no cover
    raise TypeError('Unsupported value: %s' % (obj,))


class PropertiesApi(recipe_api.RecipeApi, collections.Mapping):
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

