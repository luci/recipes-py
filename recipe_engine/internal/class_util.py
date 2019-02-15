# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Helpers for writing classes."""


def cached_property(getter):
  """A very basic @property-style decorator for read-only cached properties.

  The result of the first successful call to `getter` will be cached on `self`
  with the key _cached_property_{getter.__name__}.
  """
  key = '_cached_property_%s' % (getter.__name__,)

  @property
  def _inner(self):
    if not hasattr(self, key):
      # object.__setattr__ is needed to cheat attr.s' freeze. This is the
      # documented way to work around the lack of fine-grained immutability.
      object.__setattr__(self, key, getter(self))
    return getattr(self, key)

  return _inner
