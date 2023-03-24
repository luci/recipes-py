# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from collections import namedtuple
from itertools import chain

import abc
import os
import re

from future.utils import with_metaclass
from past.builtins import basestring

RECIPE_MODULE_PREFIX = 'RECIPE_MODULES'


def ResetTostringFns():
  RecipeConfigType._TOSTRING_MAP.clear()  # pylint: disable=W0212
  NamedBasePath._API = None


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
  subclass>.set_tostring_fn(<new method>). This new method will receive an
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
    raise NotImplementedError()

  def __str__(self):
    return self.tostring_fn(self) # pylint: disable=not-callable


class BasePath(with_metaclass(abc.ABCMeta, object)):

  @abc.abstractmethod
  def resolve(self, test_enabled):
    """Returns a string representation of the path base.

    Args:
      test_enabled (bool) - true iff this is only for recipe expectations
    """
    raise NotImplementedError()


class NamedBasePath(BasePath, namedtuple('NamedBasePath', 'name')):
  _API = None

  @classmethod
  def set_path_api(cls, api):
    cls._API = api

  def resolve(self, test_enabled):
    if self.name in self._API.c.dynamic_paths:
      return self._API.c.dynamic_paths[self.name]
    if self.name in self._API.c.base_paths:
      if test_enabled:
        return repr(self)
      return self._API.join(
          *self._API.c.base_paths[self.name])  # pragma: no cover
    raise KeyError(
        'Failed to resolve NamedBasePath: %s' % self.name)  # pragma: no cover

  def __repr__(self):
    return '[%s]' % self.name.upper()


class ModuleBasePath(BasePath, namedtuple('ModuleBasePath', 'module')):
  def resolve(self, test_enabled):
    if test_enabled:
      return repr(self)
    return os.path.dirname(self.module.__file__)  # pragma: no cover

  def __repr__(self):
    prefix = '%s.' % RECIPE_MODULE_PREFIX
    assert self.module.__name__.startswith(prefix)
    name = self.module.__name__[len(prefix):]
    # We change python's module delimiter . to ::, since . is already used
    # by expect tests.
    return 'RECIPE_MODULE[%s]' % re.sub(r'\.', '::', name)


class RecipeScriptBasePath(
    BasePath, namedtuple('RecipeScriptBasePath', 'recipe_name script_path')):
  def resolve(self, test_enabled):
    if test_enabled:
      return repr(self)
    return os.path.splitext(self.script_path)[0]+".resources" # pragma: no cover

  def __repr__(self):
    return 'RECIPE[%s].resources' % self.recipe_name


class RepoBasePath(
    BasePath, namedtuple('RepoBasePath', 'repo_name repo_root_path')):
  def resolve(self, test_enabled):
    if test_enabled:
      return repr(self)
    return self.repo_root_path  # pragma: no cover

  def __repr__(self):
    return 'RECIPE_REPO[%s]' % self.repo_name


class Path(RecipeConfigType):
  """Represents a path which is relative to a semantically-named base.

  Because there's a lot of platform (separator style) and runtime-specific
  context (working directory) which goes into assembling a final OS-specific
  absolute path, we only store three context-free attributes in this Path
  object.
  """

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
    """
    super(Path, self).__init__()
    assert isinstance(base, BasePath), base
    assert all(isinstance(x, basestring) for x in pieces), pieces
    assert not any(x in ('..', '/', '\\') for x in pieces)
    pieces = [p for p in pieces if p != '.']

    self._base = base
    self._pieces = pieces if isinstance(pieces, tuple) else tuple(pieces)
    self._platform_ext = kwargs.get('platform_ext', {})

  @property
  def base(self):
    return self._base

  @property
  def pieces(self):
    return self._pieces

  @property
  def platform_ext(self):
    return self._platform_ext

  def __eq__(self, other):
    return (self.base == other.base and
            self.pieces == other.pieces and
            self.platform_ext == other.platform_ext)

  def __hash__(self):
    return hash((
        self.base,
        self.pieces,
        tuple(sorted(self.platform_ext.items())),
    ))

  def __ne__(self, other):
    return not self == other

  def __lt__(self, other):
    if self.base != other.base:
      return self.base < other.base
    elif self.pieces != other.pieces:
      return self.pieces < other.pieces
    return (
        sorted(self.platform_ext.items()) < sorted(other.platform_ext.items())
    )

  def join(self, *pieces, **kwargs):
    """Appends *pieces to this Path, returning a new Path.

    Empty values ('', None) in pieces will be omitted.

    Args:
      pieces (tuple(str)) - The components of the path relative to base. These
        pieces must be non-relative (i.e. no '..' as a piece).

    Kwargs:
      platform_ext (dict(str, str)) - A mapping from platform name (as defined
        by the 'platform' module), to a suffix for the path.

    Returns (Path) - the new Path.
    """
    if not pieces and not kwargs:
      return self
    kwargs.setdefault('platform_ext', self.platform_ext)
    return Path(self.base, *[p for p in chain(self.pieces, pieces) if p],
                **kwargs)

  def is_parent_of(self, child):
    """True if |child| is in a subdirectory of this path."""
    # Assumes base paths are not nested.
    # TODO(vadimsh): We should not rely on this assumption.
    if self.base != child.base:
      return False
    # A path is not a parent to itself.
    if len(self.pieces) >= len(child.pieces):
      return False
    return child.pieces[:len(self.pieces)] == self.pieces

  def __repr__(self):
    s = "Path(%r" % (self.base,)
    if self.pieces:
      s += ", %s" % ", ".join(repr(x) for x in self.pieces)

    if self.platform_ext:
      platform_exts = []
      for k, v in sorted(self.platform_ext.items()):
        platform_exts.append("%s=%s" % (k, repr(v)))
      s += ", platform_exts=(%s)" % ", ".join(repr(x) for x in platform_exts)

    return s + ")"
