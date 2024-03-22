# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import collections
import itertools
from typing import Any

import abc
import os


def ResetGlobalVariableAssignments():
  RecipeConfigType._TOSTRING_MAP.clear()  # pylint: disable=W0212
  NamedBasePath._API = None


class RecipeConfigType:
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


class BasePath(metaclass=abc.ABCMeta):

  @abc.abstractmethod
  def resolve(self, test_enabled: bool) -> str:
    """Returns a string representation of the path base.

    Args:
      test_enabled: True iff this is only for recipe expectations.

    Raises:
      NotImplementedError: If this method isn't overridden by a subclass.
    """
    raise NotImplementedError()


class NamedBasePath(BasePath, collections.namedtuple('NamedBasePath', 'name')):
  _API = None

  @classmethod
  def set_path_api(cls, api):
    cls._API = api

  def resolve(self, test_enabled: bool) -> str:
    if self.name == self._API.CheckoutPathName:
      checkout_dir = self._API.checkout_dir
      # TODO: Enable this exception check.
      # if checkout_dir is None:
      #  raise ValueError(
      #      f'Cannot resolve NamedBasePath({self.name!r}) - api.path.checkout_dir is unset.')
      return str(checkout_dir)

    if self.name in self._API.c.base_paths:
      if test_enabled:
        return repr(self)
      return self._API.join(
          *self._API.c.base_paths[self.name])  # pragma: no cover

    raise KeyError(
        'Failed to resolve NamedBasePath: %s' % self.name)  # pragma: no cover

  def __repr__(self):
    return '[%s]' % self.name.upper()


class ModuleBasePath(BasePath, collections.namedtuple('ModuleBasePath',
                                                      'module')):

  def resolve(self, test_enabled):
    if test_enabled:
      return repr(self)
    return self.module.path  # pragma: no cover

  def __repr__(self):
    # We change python's module delimiter . to ::, since . is already used
    # by expect tests.
    return f'RECIPE_MODULE[{self.module.repo.name}::{self.module.name}]'


class RecipeScriptBasePath(BasePath,
                           collections.namedtuple('RecipeScriptBasePath',
                                                  'recipe_name script_path')):

  def resolve(self, test_enabled):
    if test_enabled:
      return repr(self)
    return os.path.splitext(
        self.script_path)[0] + '.resources'  # pragma: no cover

  def __repr__(self):
    return 'RECIPE[%s].resources' % self.recipe_name


class RepoBasePath(BasePath,
                   collections.namedtuple('RepoBasePath',
                                          'repo_name repo_root_path')):

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

  def __init__(self,
               base: BasePath,
               *pieces: str):
    """Creates a Path.

    Args:
      base: The 'name' of a base path, to be filled in at recipe runtime
        by the 'path' recipe module.
      *pieces: The components of the path relative to base. These pieces must
        be non-relative (i.e. no '..' or '.', etc. as a piece).
    """
    super().__init__()
    assert isinstance(base, BasePath), base
    assert all(isinstance(x, str) for x in pieces), pieces
    assert not any(x in ('..', '/', '\\') for x in pieces)

    self._base = base
    self._pieces = tuple(p for p in pieces if p != '.')

  @property
  def base(self) -> BasePath:
    return self._base

  @property
  def pieces(self) -> tuple[str, ...]:
    return self._pieces

  def __eq__(self, other: Path) -> bool:
    return (self.base == other.base and
            self.pieces == other.pieces)

  def __hash__(self) -> int:
    return hash((
        self.base,
        self.pieces,
    ))

  def __ne__(self, other: Any) -> bool:
    return not self == other

  def __lt__(self, other: Path) -> bool:
    if self.base != other.base:
      # NOTE: bases all happen to extend namedtuple, which makes this comparison
      # work.
      return self.base < other.base
    return self.pieces < other.pieces

  def __truediv__(self, piece: str) -> Path:
    """Adds the shorthand '/'-operator for .join(), returning a new path."""
    return self.join(piece)

  def join(self, *pieces: str) -> Path:
    """Appends *pieces to this Path, returning a new Path.

    Empty values ('', None) in pieces will be omitted.

    Args:
      pieces: The components of the path relative to base. These pieces must be
        non-relative (i.e. no '..' as a piece).

    Returns:
      The new Path.
    """
    if not pieces:
      return self
    return Path(
        self.base,
        *[p for p in itertools.chain(self.pieces, pieces) if p])

  def is_parent_of(self, child: Path) -> bool:
    """True if |child| is in a subdirectory of this path."""
    # Assumes base paths are not nested.
    # TODO(vadimsh): We should not rely on this assumption.
    if self.base != child.base:
      return False
    # A path is not a parent to itself.
    if len(self.pieces) >= len(child.pieces):
      return False
    return child.pieces[:len(self.pieces)] == self.pieces

  def separate(self, separator: str) -> None:
    """Breaks apart any pieces of self.pieces containing the separator.

    Example: If self.pieces is ('foo', 'bar/baz') and separator='/', then
    self.pieces will be transformed into ('foo', 'bar', 'baz'). This allows for
    more accurate comparisons, like equality or parenthood.

    Args:
      separator: The file separator character for this platform: '/' for POSIX,
        '\\' for Windows. Usually fetched via api.path.sep.
    """
    self._pieces = sum((tuple(piece.split(separator)) for piece in self.pieces),
                       start=())

  def __repr__(self) -> str:
    s = 'Path(%r' % (self.base,)
    if self.pieces:
      s += ', %s' % ', '.join(repr(x) for x in self.pieces)
    return s + ')'
