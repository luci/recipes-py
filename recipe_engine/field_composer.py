# Copyright 2013-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


class FieldComposerError(BaseException):
  """Base error class for this module."""
  pass


class RegistryConflict(FieldComposerError):
  pass


class DegenerateRegistryError(FieldComposerError):
  pass


class CompositionUndefined(FieldComposerError):
  pass


class FieldComposer(object):

  def __init__(self, fields, registered_functors):
    """Initialize the internal registry mapping names to functors."""
    try:
      self._registry = {
        name: {'combine': value['combine']}
        for name, value in registered_functors.iteritems()}
    except KeyError:
      raise DegenerateRegistryError(
          'Registry entries must contain key "combine."')
    self._fields = fields

  def __contains__(self, key):
    return key in self._fields

  def __getitem__(self, key):
    return self._fields[key]

  def get(self, index, default=None):
    """Wrapper for self._fields.get."""
    return self._fields.get(index, default)

  def iteritems(self):
    """Wrapper for self._fields.iteritems."""
    return self._fields.iteritems()

  def compose(self, second_compositor):
    """Return the monoidal composition of two FieldComposers."""
    # If second_compositor is a FieldComposer, registries shouldn't conflict.
    if isinstance(second_compositor, dict):
      second_compositor = FieldComposer(second_compositor, {})
    new_registry = self._registry.copy()
    second_registry = second_compositor._registry
    for key, value in second_registry.iteritems():
      if key in self._registry and value != self._registry[key]:
        raise RegistryConflict('Conflicting values for key %s.' % key)
      new_registry[key] = value

    # populate new field dictionary with composed values
    all_keys = set().union(self._fields, second_compositor._fields)
    new_fields = {}
    for name in all_keys:
      if name not in new_registry:
        raise CompositionUndefined(
            "No combine function registered for %s." % name)
      if name in second_compositor:
        new_value = self.get_with_context(name, second_compositor[name])
      else:
        # Name is in exactly one compositor, so get that value.
        new_value = self[name]
      new_fields[name] = new_value

    # create and return the new compositor
    return FieldComposer(new_fields, new_registry)

  def get_with_context(self, key, value):
    """Combine the current value for key (if any) with value."""
    if key not in self._registry:
      raise CompositionUndefined(
          "No combine function registered for %s." % key)
    if key in self:
      return self._registry[key]['combine'](self.get(key), value)
    return value
