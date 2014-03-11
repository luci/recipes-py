# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

def ResetTostringFns():
  RecipeConfigType._TOSTRING_MAP.clear()  # pylint: disable=W0212


def json_fixup(obj):
  if isinstance(obj, RecipeConfigType):
    return str(obj)
  raise TypeError("%r is not JSON serializable" % obj)


class RecipeConfigType(object):
  """Base class for custom Recipe config types, intended to be subclassed.

  RecipeConfigTypes are meant to be PURE data. There should be no dependency on
  any external systems (i.e. no importing sys, os, etc.).

  The subclasses should override default_tostring_fn. This method should
  produce a string representation of the object. This string representation
  should contain all of the data members of the subclass. This representation
  will be used during the execution of the recipe_config_tests.

  External entities (usually recipe modules), can override the default
  tostring_fn method by calling <RecipeConfigType
  subclass>.set_tostring_fn(<new method>). This new method will recieve an
  instance of the RecipeConfigType subclass as its single argument, and is
  expected to return a string. There is no restriction on the data that the
  override tostring_fn may use. For example, the Path class in this module has
  its tostring_fn overridden by the 'path' recipe_module.  This new tostring_fn
  uses data from the current recipe run, like the host os, to return platform
  specific strings using the data in the Path object.
  """
  _TOSTRING_MAP = {}

  @property
  def tostring_fn(self):
    cls = self.__class__
    return self._TOSTRING_MAP.get(cls.__name__, cls.default_tostring_fn)

  @classmethod
  def set_tostring_fn(cls, new_tostring_fn):
    assert cls.__name__ not in cls._TOSTRING_MAP, (
        'tostring_fn already installed for %s' % cls)
    cls._TOSTRING_MAP[cls.__name__] = new_tostring_fn

  def default_tostring_fn(self):
    raise NotImplementedError

  def __str__(self):
    return self.tostring_fn(self)


class Path(RecipeConfigType):
  """Represents a path which is relative to a semantically-named base.

  Because there's a lot of platform (separator style) and runtime-specific
  context (working directory) which goes into assembling a final OS-specific
  absolute path, we only store three context-free attributes in this Path
  object.
  """
  # Restrict basenames to '[ALL_CAPS]'. This will help catch
  # errors if someone attempts to provide an actual string path '/some/example'
  # as the 'base'.
  BASE_RE = re.compile('\[([A-Z][A-Z_]*)\]')

  def __init__(self, base, *pieces, **kwargs):
    """Creates a Path

    Args:
      base (str) - The 'name' of a base path, to be filled in at recipe runtime
        by the 'path' recipe module.
      pieces (tuple(str)) - The components of the path relative to base. These
        pieces must be non-relative (i.e. no '..' or '.', etc. as a piece).

    Kwargs:
      platform_ext (dict(str, str)) - A mapping from platform name (as defined
        by the 'platform' module), to a suffix for the path.
      _bypass (bool) - Bypass the type checking and use |base| directly. Don't
        use this outside of the 'path' module or this class.
    """
    super(Path, self).__init__()
    assert all(isinstance(x, basestring) for x in pieces), pieces
    assert not any(x in ('..', '.', '/', '\\') for x in pieces)
    self.pieces = pieces

    if kwargs.get('_bypass'):
      self.base = base
    else:
      base_match = self.BASE_RE.match(base)
      assert base_match, 'Base should be [ALL_CAPS], got %r' % base
      self.base = base_match.group(1).lower()

    self.platform_ext = kwargs.get('platform_ext', {})

  def join(self, *pieces, **kwargs):
    kwargs.setdefault('platform_ext', self.platform_ext)
    kwargs['_bypass'] = True
    return Path(self.base, *filter(bool, self.pieces + pieces), **kwargs)

  def __call__(self, *pieces, **kwargs):
    return self.join(*pieces, **kwargs)

  def default_tostring_fn(self):
    suffix = ''
    if self.platform_ext:
      suffix = ', platform_ext=%r' % (self.platform_ext,)
    pieces = ''
    if self.pieces:
      pieces = ', ' + (', '.join(map(repr, self.pieces)))
    return 'Path(\'[%s]\'%s%s)' % (self.base.upper(), pieces, suffix)
