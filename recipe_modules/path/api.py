# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""All functions related to manipulating paths in recipes.

Recipes handle paths a bit differently than python does. All path manipulation
in recipes revolves around Path objects. These objects store a base path (always
absolute), plus a list of components to join with it. New paths can be derived
by calling the .join method with additional components.

In this way, all paths in Recipes are absolute, and are constructed from a small
collection of anchor points. The built-in anchor points are:
  * `api.path['start_dir']` - This is the directory that the recipe started in.
    it's similar to `cwd`, except that it's constant.
  * `api.path['cache']` - This directory is provided by whatever's running the
    recipe. Files and directories created under here /may/ be evicted in between
    runs of the recipe (i.e. to relieve disk pressure).
  * `api.path['cleanup']` - This directory is provided by whatever's running the
    recipe. Files and directories created under here /are guaranteed/ to be
    evicted in between runs of the recipe. Additionally, this directory is
    guaranteed to be empty when the recipe starts.
  * `api.path['tmp_base']` - This directory is the system-configured temp dir.
    This is a weaker form of 'cleanup', and its use should be avoided. This may
    be removed in the future (or converted to an alias of 'cleanup').
  * `api.path['checkout']` - This directory is set by various checkout modules
    in recipes. It was originally intended to make recipes easier to read and
    make code somewhat generic or homogeneous, but this was a mistake. New code
    should avoid 'checkout', and instead just explicitly pass paths around. This
    path may be removed in the future.

There are other anchor points which can be defined (e.g. by the
`depot_tools/infra_paths` module). Refer to those modules for additional
documentation.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
import copy
import enum
import itertools
import os
import re
import tempfile
import types
from typing import Any, Callable, Literal, cast

from recipe_engine import recipe_api, recipe_test_api
from recipe_engine import config_types


class FileType(enum.Enum):
  FILE = 1
  DIRECTORY = 2

CheckoutPathName = 'checkout'


class Error(Exception):
  """Error specific to path recipe module."""


def PathToString(api, test):

  def PathToString_inner(path):
    assert isinstance(path, config_types.Path)
    return api.join(path.base.resolve(test.enabled), *path.pieces)

  return PathToString_inner


class path_set:
  """Implements a set which contains all the parents folders of added
  folders."""

  # TODO(iannucci): Expand this to be a full fakey filesystem, including file
  # contents and file types. Coordinate with the `file` module.
  def __init__(self, path_mod: fake_path, initial_paths):
    self._path_mod: types.ModuleType = path_mod
    self._initial_paths: set[config_types.Path]|None = set(initial_paths)
    # An entry in self._paths means an object exists in the mock filesystem.
    # The value (either FILE or DIRECTORY) is the type of that object.
    self._paths: dict[config_types.Path, FileType] = {}

  def _initialize(self) -> None:  # pylint: disable=method-hidden
    self._initialize: Callable[[], None] = lambda: None
    for path in self._initial_paths:
      self.add(path, FileType.FILE)
    self._initial_paths = None
    self.contains: Callable[[config_types.Path], bool] = (
        lambda path: path in self._paths
    )

  @property
  def _separator(self) -> str:
    return self._path_mod.sep

  def _is_contained_in(self, path: config_types.Path,
                       root: config_types.Path, match_root: bool) -> bool:
    if not path.startswith(root):
      return False
    if len(path) == len(root):
      return match_root
    return path[len(root)] == self._separator

  def add(self, path: config_types.Path, kind: FileType):
    path = str(path)
    self._initialize()
    prev_path: str|None = None
    while path != prev_path:
      self._paths[path] = kind
      prev_path, path = path, self._path_mod.dirname(path)
      kind = FileType.DIRECTORY

  def copy(self, source: config_types.Path, dest: config_types.Path) -> None:
    source, dest = str(source), str(dest)
    self._initialize()
    to_add: dict[str, FileType] = {}
    for p in self._paths:
      if self._is_contained_in(p, source, match_root=True):
        to_add[p.replace(source, dest)] = self._paths[p]
    for path, kind in to_add.items():
      self.add(path, kind)

  def remove(self, path: config_types.Path,
             filt: Callable[[config_types.Path], bool]) -> None:
    path: str = str(path)
    self._initialize()
    match_root: bool = True
    if path[-1] == self._separator:
      match_root = False
      path: str = path.rstrip(self._separator)
    kill_set: set[config_types.Path] = set(
        p for p in self._paths
        if self._is_contained_in(p, path, match_root) and filt(p))
    for entry in kill_set:
      del self._paths[entry]

  # pylint: disable=method-hidden
  def contains(self, path: config_types.Path) -> bool:
    self._initialize()
    return self.contains(path)

  def kind(self, path: config_types.Path) -> FileType:
    self._initialize()
    return self._paths[path]


import ntpath
import posixpath
PathCommonModule = Literal[ntpath, posixpath]


class fake_path:
  """Standin for os.path when we're in test mode.

  This class simulates the os.path interface exposed by PathApi, respecting the
  current platform according to the `platform` module. This allows us to
  simulate path functions according to the platform being tested, rather than
  the platform which is currently running.
  """

  def __init__(self, is_windows: bool, _mock_path_exists):
    if is_windows:
      import ntpath as pth
    else:
      import posixpath as pth

    self._pth: PathCommonModule = pth
    self._mock_path_exists = path_set(self, _mock_path_exists)

  def __getattr__(self, name: str) -> Any:
    return getattr(self._pth, name)

  def mock_add_paths(self, path: config_types.Path, kind: FileType) -> None:
    """Adds a path and all of its parents to the set of existing paths."""
    assert kind in FileType
    self._mock_path_exists.add(path, kind)

  def mock_copy_paths(self, source: config_types.Path,
                      dest: config_types.Path) -> None:
    """Duplicates a path and all of its children to another path."""
    self._mock_path_exists.copy(source, dest)

  def mock_remove_paths(self, path: config_types.Path,
                        filt: Callable[[config_types.Path], bool]) -> None:
    """Removes a path and all of its children from the set of existing paths."""
    self._mock_path_exists.remove(path, filt)

  def exists(self, path: config_types.Path) -> bool:  # pylint: disable=E0202
    """Returns True if path refers to an existing path."""
    return self._mock_path_exists.contains(path)

  def isdir(self, path: config_types.Path) -> bool:
    return (self.exists(path) and
            self._mock_path_exists.kind(path) == FileType.DIRECTORY)

  def isfile(self, path: config_types.Path) -> bool:
    return (self.exists(path) and
            self._mock_path_exists.kind(path) == FileType.FILE)

  # This matches:
  #   [START_DIR]
  #   RECIPE[some_pkg::some_module:recipe_name]
  #
  # and friends at the beginning of a string.
  ROOT_MATCHER = re.compile(r'^[A-Z_]*\[[^]]*\]')

  def normpath(self, path: config_types.Path) -> config_types.Path:
    """Normalizes the path.

    This splits off a recipe base (i.e. RECIPE[...]) so that normpath is
    only called on the user-supplied portion of the path.
    """
    real_normpath = self._pth.normpath
    m = self.ROOT_MATCHER.match(path)
    if m:
      prefix = m.group(0)
      rest = path[len(prefix):]
      if rest == '':
        # normpath turns '' into '.'
        return prefix
      return prefix + real_normpath(rest)
    return real_normpath(path)

  def abspath(self, path: config_types.Path) -> config_types.Path:
    """Returns the absolute version of path."""
    return self.normpath(path)

  def realpath(self, path: config_types.Path) -> config_types.Path:
    """Returns the canonical version of the path."""
    return self.normpath(path)


class PathApi(recipe_api.RecipeApi):
  _paths_client = recipe_api.RequireClient('paths')

  # This is the literal string 'checkout'.
  #
  # This is only being added as an intermediate step to removing the
  # dictionary-like API from the path module, and will be removed in the near
  # future. Do not use this.
  #
  # Use the .checkout_dir @property directly, instead.
  CheckoutPathName = CheckoutPathName

  def get_config_defaults(self) -> dict[str, Any]:
    """Internal recipe implementation function."""
    # TODO(iannucci): Completely remove config from path.
    return {
        'START_DIR': self._startup_cwd,
        'TEMP_DIR': self._temp_dir,
        'CACHE_DIR': self._cache_dir,
        'CLEANUP_DIR': self._cleanup_dir,
        'HOME_DIR': self._home_dir,
    }

  def __init__(self, path_properties, **kwargs):
    super().__init__(**kwargs)
    config_types.Path.set_tostring_fn(PathToString(self, self._test_data))
    config_types.NamedBasePath.set_path_api(self)

    self._path_properties = path_properties

    # Assigned at "initialize".
    # NT or POSIX path module, or "os.path" in prod.
    self._path_mod: ModuleType|None = None
    self._startup_cwd: config_types.Path|None = None
    self._temp_dir: config_types.Path|None = None
    self._cache_dir: config_types.Path|None = None
    self._cleanup_dir: config_types.Path|None = None
    self._home_dir: config_types.Path|None = None

    # checkout_dir can be set at most once per recipe run.
    self._checkout_dir: config_types.Path|None = None

    # Used in mkdtemp and mkstemp when generating and checking expectations.
    self._test_counter: collections.Counter = collections.Counter()

  def _read_path(self, property_name, default):  # pragma: no cover
    """Reads a path from a property. If absent, returns the default.

    Validates that the path is absolute.
    """
    value = self._path_properties.get(property_name)
    if not value:
      assert os.path.isabs(default), default
      return default
    if not os.path.isabs(value):
      raise Error('Path "%s" specified by module property %s is not absolute' %
                  (value, property_name))
    return value

  def _ensure_dir(self, path: str) -> None:  # pragma: no cover
    os.makedirs(path, exist_ok=True)

  def _split_path(self, path: config_types.Path
                  ) -> tuple[str, ...]:  # pragma: no cover
    """Relative or absolute path -> tuple of components."""
    abs_path: list[str, ...] = os.path.abspath(path).split(self.sep)
    # Guarantee that the first element is an absolute drive or the posix root.
    if abs_path[0].endswith(':'):
      abs_path[0] += '\\'
    elif abs_path[0] == '':
      abs_path[0] = '/'
    else:
      assert False, 'Got unexpected path format: %r' % abs_path
    return tuple(abs_path)

  def initialize(self) -> None:
    """Internal recipe implementation function."""
    if not self._test_data.enabled:  # pragma: no cover
      self._path_mod: ModuleType = os.path
      start_dir = self._paths_client.start_dir
      self._startup_cwd = self._split_path(start_dir)
      self._home_dir = self._split_path(self._path_mod.expanduser('~'))

      tmp_dir = self._read_path('temp_dir', tempfile.gettempdir())
      self._ensure_dir(tmp_dir)
      self._temp_dir = self._split_path(tmp_dir)

      cache_dir = self._read_path('cache_dir', os.path.join(start_dir, 'cache'))
      self._ensure_dir(cache_dir)
      self._cache_dir = self._split_path(cache_dir)

      # If no cleanup directory is specified, assume that any directory
      # underneath of the working directory is transient and will be purged in
      # between builds.
      cleanup_dir = self._read_path('cleanup_dir',
                                    os.path.join(start_dir, 'recipe_cleanup'))
      self._ensure_dir(cleanup_dir)
      self._cleanup_dir = self._split_path(cleanup_dir)
    else:
      tdata = cast(recipe_test_api.ModuleTestData, self._test_data)
      # HACK: The platform test_api sets platform.name specifically for the
      # path module when users use api.platform.name(...) in their tests.
      # This is dirty, but it avoids a LOT of interdependency complexity.
      #
      # In the current version of this code, we initialize _path_mod in
      # `initialize` (rather than __init__) which is already late, but we also
      # are calling the set_tostring_fn and set_path_api global variable hacks
      # in __init__ which globally modify the behavior of NamedBasePath and Path
      # across the entire process.
      #
      # In a subsequent CL, we will be able to move _path_mod initialization
      # into __init__, and remove the set_tostring_fn/set_path_api
      # interdependency, and we will also be able to return fully-encapsulated
      # Path objects from this module.
      is_windows: bool = tdata.get('platform.name', 'linux') == 'win'

      self._path_mod = fake_path(is_windows, tdata.get('exists', []))

      root: str = 'C:\\' if is_windows else '/'
      self._startup_cwd = [root, 'b', 'FakeTestingCWD']
      # Appended to placeholder '[TMP]' to get fake path in test.
      self._temp_dir = [root]
      self._cache_dir = [root, 'b', 'c']
      self._cleanup_dir = [root, 'b', 'cleanup']
      self._home_dir = [root, 'home', 'fake_user']

    self.set_config('BASE')

  def assert_absolute(self, path: config_types.Path | str) -> None:
    """Raises AssertionError if the given path is not an absolute path.

    Args:
      * path - The path to check.
    """
    if self.abspath(path) != str(path):
      raise AssertionError('%s is not absolute' % path)

  def mkdtemp(self, prefix: str = tempfile.template) -> config_types.Path:
    """Makes a new temporary directory, returns Path to it.

    Args:
      * prefix - a tempfile template for the directory name (defaults to "tmp").

    Returns a Path to the new directory.
    """
    if not self._test_data.enabled:  # pragma: no cover
      # New path as str.
      new_path = tempfile.mkdtemp(prefix=prefix, dir=str(self['cleanup']))
      # Ensure it's under self._cleanup_dir, convert to Path.
      new_path = self._split_path(new_path)
      assert new_path[:len(self._cleanup_dir)] == self._cleanup_dir, (
          'new_path: %r -- cleanup_dir: %r' % (new_path, self._cleanup_dir))
      temp_dir = self['cleanup'].join(*new_path[len(self._cleanup_dir):])
    else:
      self._test_counter[prefix] += 1
      assert isinstance(prefix, str)
      temp_dir = self['cleanup'].join('%s_tmp_%d' %
                                      (prefix, self._test_counter[prefix]))
    self.mock_add_paths(temp_dir, FileType.DIRECTORY)
    return temp_dir

  def mkstemp(self, prefix: str = tempfile.template) -> config_types.Path:
    """Makes a new temporary file, returns Path to it.

    Args:
      * prefix - a tempfile template for the file name (defaults to "tmp").

    Returns a Path to the new file. Unlike tempfile.mkstemp, the file's file
    descriptor is closed.
    """
    if not self._test_data.enabled:  # pragma: no cover
      # New path as str.
      fd, new_path = tempfile.mkstemp(prefix=prefix, dir=str(self['cleanup']))
      # Ensure it's under self._cleanup_dir, convert to Path.
      split_path: list[str] = self._split_path(new_path)
      assert split_path[:len(self._cleanup_dir)] == self._cleanup_dir, (
          'new_path: %r -- cleanup_dir: %r' % (split_path, self._cleanup_dir))
      temp_file: config_types.Path = self['cleanup'].join(
          *split_path[len(self._cleanup_dir):])
      os.close(fd)
    else:
      self._test_counter[prefix] += 1
      assert isinstance(prefix, str)
      temp_file: config_types.Path = self['cleanup'].join(
          '%s_tmp_%d' % (prefix, self._test_counter[prefix]))
    self.mock_add_paths(temp_file, FileType.FILE)
    return temp_file

  def abs_to_path(self, abs_string_path: str) -> config_types.Path:
    """Converts an absolute path string `abs_string_path` to a real Path
    object, using the most appropriate known base path.

      * abs_string_path MUST be an absolute path
      * abs_string_path MUST be rooted in one of the configured base paths known
        to the path module.

    This method will find the longest match in all the following:
      * module resource paths
      * recipe resource paths
      * repo paths
      * checkout_dir
      * base_paths

    Example:
    ```
    # assume [START_DIR] == "/basis/dir/for/recipe"
    api.path.abs_to_path("/basis/dir/for/recipe/some/other/dir") ->
      Path("[START_DIR]/some/other/dir")
    ```

    Raises an ValueError if the preconditions are not met, otherwise returns the
    Path object.
    """
    if isinstance(abs_string_path, config_types.Path):
      return abs_string_path

    ap = self.abspath(abs_string_path)
    if ap != abs_string_path:
      raise ValueError("path is not absolute: %r v %r" % (abs_string_path, ap))

    # try module/recipe/repo resource paths first
    sPath, path = self._paths_client.find_longest_prefix(
        abs_string_path, self.sep)
    if path is None:
      # try base paths now
      for path_name in itertools.chain((CheckoutPathName,), self.c.base_paths):
        path = self[path_name]
        sPath = str(path)
        if abs_string_path.startswith(sPath):
          break
      else:
        path = None

    if path is None:
      raise ValueError("could not figure out a base path for %r" %
                       abs_string_path)

    sub_path = abs_string_path[len(sPath):].strip(self.sep)
    return path.join(*sub_path.split(self.sep))

  def __contains__(self, pathname: str) -> bool:
    if pathname == CheckoutPathName:
      return bool(self.checkout_dir)
    return pathname in self.c.base_paths

  def __setitem__(self, pathname: Literal[CheckoutPathName], path: config_types.Path) -> None:
    """Sets the checkout path.

    DEPRECATED - Use `api.path.set_checkout_dir` instead.

    The only valid value of `pathname` is the literal string CheckoutPathName.
    """
    if pathname != CheckoutPathName:
      raise ValueError(
          f'The only valid dynamic path value is `checkout`. Got {pathname!r}.'
          ' Use `api.path.checkout_dir = <path>` instead.')
    self.checkout_dir = path

  @property
  def checkout_dir(self) -> config_types.Path|None:
    """Returns the Path which was assigned to this checkout_dir property."""
    return self._checkout_dir

  @checkout_dir.setter
  def checkout_dir(self, path: config_types.Path) -> None:
    """Sets the global variable `api.path.checkout_dir` to the given path.

    """
    if not isinstance(path, config_types.Path):
      raise ValueError(
          f'api.path.checkout_dir called with bad type: {path!r} ({type(path)})')

    if (current := self._checkout_dir) is not None:
      if current == path:
        return

      raise ValueError(
          f'api.path.checkout_dir can only be set once. old:{current!r} new:{path!r}')

    self._checkout_dir = path

  def get(self,
          name: str,
          default: config_types.Path|None = None) -> config_types.Path:
    """Gets the base path named `name`. See module docstring for more info."""
    if name == CheckoutPathName:
      return config_types.Path(config_types.NamedBasePath(CheckoutPathName))

    if name in self.c.base_paths:
      return config_types.Path(config_types.NamedBasePath(name))

    return default

  def __getitem__(self, name: str) -> config_types.Path:
    """Gets the base path named `name`. See module docstring for more info."""
    result = self.get(name)
    if not result:
      raise KeyError('Unknown path: %s' % name)
    return result

  @property
  def pardir(self) -> str:
    """Equivalent to os.pardir."""
    return self._path_mod.pardir

  @property
  def sep(self) -> str:
    """Equivalent to os.sep."""
    return self._path_mod.sep

  @property
  def pathsep(self) -> str:
    """Equivalent to os.pathsep."""
    return self._path_mod.pathsep

  def abspath(self, path: config_types.Path | str):
    """Equivalent to os.abspath."""
    return self._path_mod.abspath(str(path))

  def basename(self, path: config_types.Path | str):
    """Equivalent to os.path.basename."""
    return self._path_mod.basename(str(path))

  def dirname(self, path: config_types.Path | str) -> config_types.Path | str:
    """For "foo/bar/baz", return "foo/bar".

    This corresponds to os.path.dirname().

    The type of the return value matches the type of the argument.

    Args:
      path: path to take directory name of

    Returns dirname of path
    """
    if isinstance(path, config_types.Path):
      return self.abs_to_path(self._path_mod.dirname(str(path)))

    # If path is not a Path object it's likely a string. Leave return value as a
    # string.
    return self._path_mod.dirname(str(path))

  def join(self, path, *paths):
    """Equivalent to os.path.join.

    Note that Path objects returned from this module (e.g.
    api.path['start_dir']) have a built-in join method (e.g.
    new_path = p.join('some', 'name')). Many recipe modules expect Path objects
    rather than strings. Using this `join` method gives you raw path joining
    functionality and returns a string.

    If your path is rooted in one of the path module's root paths (i.e. those
    retrieved with api.path[something]), then you can convert from a string path
    back to a Path with the `abs_to_path` method.
    """
    return self._path_mod.join(str(path), *map(str, paths))

  def split(self, path):
    """For "foo/bar/baz", return ("foo/bar", "baz").

    This corresponds to os.path.split().

    The type of the first item in the return value matches the type of the
    argument.

    Args:
      path (Path or str): path to split into directory name and basename

    Returns (dirname(path), basename(path)).
    """
    dirname, basename = self._path_mod.split(str(path))
    if isinstance(path, config_types.Path):
      return (self.abs_to_path(dirname), basename)

    # If path is not a Path object it's likely a string. Leave both elements in
    # return tuple as strings.
    return (dirname, basename)

  def splitext(
      self, path: config_types.Path | str
  ) -> tuple[config_types.Path | str, str]:
    """For "foo/bar.baz", return ("foo/bar", ".baz").

    This corresponds to os.path.splitext().

    The type of the first item in the return value matches the type of the
    argument.

    Args:
      path: Path to split into name and extension

    Returns:
      (name, extension_including_dot).
    """
    name, ext = self._path_mod.splitext(str(path))
    if isinstance(path, config_types.Path):
      return (self.abs_to_path(name), ext)

    # If path is not a Path object it's likely a string. Leave both elements in
    # return tuple as strings.
    return (name, ext)

  def realpath(self, path: config_types.Path | str):
    """Equivalent to os.path.realpath."""
    return self._path_mod.realpath(str(path))

  def relpath(self, path, start):
    """Roughly equivalent to os.path.relpath.

    Unlike os.path.relpath, `start` is _required_. If you want the 'current
    directory', use the `recipe_engine/context` module's `cwd` property.
    """
    return self._path_mod.relpath(str(path), str(start))

  def normpath(self, path):
    """Equivalent to os.path.normpath."""
    return self._path_mod.normpath(str(path))

  def expanduser(self, path):  # pragma: no cover
    """Do not use this, use `api.path['home']` instead.

    This ONLY handles `path` == "~", and returns `str(api.path['home'])`.
    """
    if path == "~":
      return str(self['home'])
    raise ValueError("expanduser only supports `~`.")

  def exists(self, path):
    """Equivalent to os.path.exists.

    The presence or absence of paths can be mocked during the execution of the
    recipe by using the mock_* methods.
    """
    return self._path_mod.exists(str(path))

  def isdir(self, path):
    """Equivalent to os.path.isdir.

    The presence or absence of paths can be mocked during the execution of the
    recipe by using the mock_* methods.
    """
    return self._path_mod.isdir(str(path))

  def isfile(self, path):
    """Equivalent to os.path.isfile.

    The presence or absence of paths can be mocked during the execution of the
    recipe by using the mock_* methods.
    """
    return self._path_mod.isfile(str(path))

  def mock_add_paths(self, path: config_types.Path,
                     kind: FileType = FileType.FILE) -> None:
    """For testing purposes, mark that |path| exists."""
    if self._test_data.enabled:
      self._path_mod.mock_add_paths(path, kind)

  def mock_add_file(self, path: config_types.Path) -> None:
    """For testing purposes, mark that file |path| exists."""
    self.mock_add_paths(path, FileType.FILE)

  def mock_add_directory(self, path: config_types.Path) -> None:
    """For testing purposes, mark that file |path| exists."""
    self.mock_add_paths(path, FileType.DIRECTORY)

  def mock_copy_paths(self, source: config_types.Path,
                      dest: config_types.Path) -> None:
    """For testing purposes, copy |source| to |dest|."""
    if self._test_data.enabled:
      self._path_mod.mock_copy_paths(source, dest)

  def mock_remove_paths(
      self,
      path: config_types.Path,
      should_remove: Callable[[str], bool] = lambda p: True) -> None:
    """For testing purposes, mark that |path| doesn't exist.

    Args:
      path: The path to remove.
      should_remove: Called for every candidate path. Return True to remove this
        path.
    """
    if self._test_data.enabled:
      self._path_mod.mock_remove_paths(path, should_remove)

  def separate(self, path: config_types.Path) -> None:
    """Separate a path's pieces in-place with this platform's separator char."""
    path.separate(self.sep)

  def eq(self, path1: config_types.Path, path2: config_types.Path) -> bool:
    """Check whether path1 points to the same path as path2.

    Under most circumstances, path equality is checked via `path1 == path2`.
    However, if the paths are constructed via differently joined dirs, such as
    ('foo' / 'bar') vs. ('foo/bar'), that doesn't work. This method addresses
    that problem by creating copies of the paths, and then separating them
    according to self.sep. The original paths are not modified.
    """
    path1_copy = copy.deepcopy(path1)
    path2_copy = copy.deepcopy(path2)
    self.separate(path1_copy)
    self.separate(path2_copy)
    return path1_copy == path2_copy

  def is_parent_of(self, parent: config_types.Path,
                   child: config_types.Path) -> bool:
    """Check whether child is contained within parent.

    Under most circumstances, this would be checked via
    `parent.is_parent_of(child)`. However, if the paths are constructed via
    differently joined dirs, such as ('foo', 'bar') vs. ('foo/bar', 'baz.txt'),
    that doesn't work. This method addresses that problem by creating copies of
    the paths, and then separating them according to self.sep. The original
    paths are not modified.
    """
    parent_copy = copy.deepcopy(parent)
    child_copy = copy.deepcopy(child)
    self.separate(parent_copy)
    self.separate(child_copy)
    return parent_copy.is_parent_of(child_copy)
