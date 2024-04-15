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
  * `api.path.start_dir` - This is the directory that the recipe started in.
    it's similar to `cwd`, except that it's constant.
  * `api.path.cache_dir` - This directory is provided by whatever's running the
    recipe. Files and directories created under here /may/ be evicted in between
    runs of the recipe (i.e. to relieve disk pressure).
  * `api.path.cleanup_dir` - This directory is provided by whatever's running the
    recipe. Files and directories created under here /are guaranteed/ to be
    evicted in between runs of the recipe. Additionally, this directory is
    guaranteed to be empty when the recipe starts.
  * `api.path.tmp_base_dir` - This directory is the system-configured temp dir.
    This is a weaker form of 'cleanup', and its use should be avoided. This may
    be removed in the future (or converted to an alias of 'cleanup').
  * `api.path.checkout_dir` - This directory is set by various checkout modules
    in recipes. It was originally intended to make recipes easier to read and
    make code somewhat generic or homogeneous, but this was a mistake. New code
    should avoid 'checkout', and instead just explicitly pass paths around. This
    path may be removed in the future.
"""

from __future__ import annotations

import collections
import enum
import ntpath
import os
import posixpath
import re
import tempfile

from typing import Any, Callable, Literal

from recipe_engine import recipe_api, recipe_test_api
from recipe_engine import config_types

from . import test_api


class FileType(enum.Enum):
  FILE = 1
  DIRECTORY = 2

CheckoutPathName = 'checkout'
CheckoutPathNameType = Literal['checkout']
NamedBasePathsType = CheckoutPathNameType | Literal[
    'cache',
    'cleanup',
    'home',
    'start_dir',
    'tmp_base',
]


def _cast_to_path_impl(path_mod, strpath: str) -> config_types.Path:
  """This is the core implementation of 'cast_to_path'.

  This exists outside of PathApi, because it's also used to rationalize
  UnvalidatedPaths in path_set.

  The `path_mod` argument is always effectively either the
  ntpath or posixpath module via either fake_path.__getattr__ in the path_set
  case, or directly via PathApi._path_mod in the testing/production case.
  Unfortunately, this is not currently expressible as a type annotation, because
  modules are not allowed as types (even though logically they are representable
  as a Protocol).

  This converts the string path to a Path using the current real/simulated
  platform's implementation of splitdrive to form a ResolvedBasePath on the
  'drive', with the rest of the path being split into pieces using the default
  config_types.Path constructor logic (i.e. using platform-aware path slash).
  """
  drive, path = path_mod.splitdrive(strpath)
  # NOTE(crbug.com/329113288) - this should switch to isabs when we change
  # config_types.Path to pathlib.Path. Currently isabs does the wrong thing with
  # testing path roots like [CACHE], and ntpath.abspath won't add a fake drive
  # (meaning that abspath(strpath) == strpath is not a good check.
  if path_mod.sep == '\\':
    if not drive:
      raise ValueError(
          f'Cannot use {strpath!r} with cast_to_path - not absolute.')
  else:
    if not strpath.startswith('/'):
      raise ValueError(
          f'Cannot use {strpath!r} with cast_to_path - not absolute.')
  return config_types.Path(config_types.ResolvedBasePath(drive), path)


class path_set:
  """Implements a set which contains all the parents folders of added
  folders.

  This all boils down to a flat, sorted, list of (strpath, kind) pairs, where kind
  is reductively just FILE or DIRECTORY. This is a far cry from a real
  filesystem. See crbug.com/40890779.

  The initial set of paths is populated via the PathTestApi's files_exist and
  dirs_exist module data. These can either be regular config_types.Path
  instances, based on a ResolvedBasePath or on a CheckoutBasePath, OR they can
  be UnvalidatedPath instances, which path_set will validate and cast into
  a config_types.Path prior to ingestion.

  Paths based on CheckoutBasePath will be held in limbo in the _checkout_paths
  attribute until the recipe assigns a concrete Path for checkout_dir, at which
  point these buffered Paths will now spring into existence. This is definitely
  abstraction-breaking, but some downstream recipes depend on this behavior, so
  it will all need to be untangled carefully.
  """

  # BUG(crbug.com/40890779): Expand this to be a full fakey filesystem, including file
  # contents and file types. Coordinate with the `file` module.
  def __init__(self, path_mod: fake_path,
               test_data: recipe_test_api.ModuleTestData):

    # path_set is only ever used in the testing paths, so we know _path_mod is
    # always a fake_path.
    self._path_mod: fake_path = path_mod

    # _checkout_paths are buffered until `mark_checkout_dir_set` has been called,
    # at which point we know it's acceptable to render these Paths to strings.
    self._checkout_paths: list[tuple[config_types.Path, FileType]] = []

    initial_paths: list[tuple[config_types.Path, FileType]] = []
    for filepath in test_data.get('files_exist', ()):
      if isinstance(filepath, test_api.UnvalidatedPath):
        filepath = _cast_to_path_impl(path_mod,
                                      filepath.base).joinpath(*filepath.pieces)
      assert isinstance(filepath, config_types.Path), (
          f'path.files_exist module test data contains non-Path {type(filepath)}'
      )
      initial_paths.append((filepath, FileType.FILE))

    for dirpath in test_data.get('dirs_exist', ()):
      if isinstance(dirpath, test_api.UnvalidatedPath):
        dirpath = _cast_to_path_impl(path_mod,
                                     dirpath.base).joinpath(*dirpath.pieces)
      assert isinstance(dirpath, config_types.Path), (
          f'path.files_exist module test data contains non-Path {type(dirpath)}'
      )
      initial_paths.append((dirpath, FileType.DIRECTORY))

    # An entry in self._paths means an object exists in the mock filesystem.
    # The value (either FILE or DIRECTORY) is the type of that object.
    self._paths: dict[str, FileType] = {}
    for path, kind in initial_paths:
      if not isinstance(path, config_types.Path):  # pragma: no cover
        raise ValueError(
            'String paths to `api.path.exists` in GenTests are not allowed.'
            ' Use one of the _dir properties on `api.path` to get a Path, or '
            ' use `api.path.cast_to_path`.')

      if isinstance(path.base, config_types.CheckoutBasePath):
        self._checkout_paths.append((path, kind))
      else:
        self.add(path, kind)

  def mark_checkout_dir_set(self) -> None:
    """This is called by PathApi once when checkout_dir is initially assigned to
    a concrete Path.

    Note that a side-effect of the assignment in PathApi is updating the
    CheckoutBasePath._resolved class variable, which makes it possible to render
    the Paths in _checkout_paths to strings.
    """
    for path, kind in self._checkout_paths:
      self.add(path, kind)
    self._checkout_paths.clear()

  def _is_contained_in(self, path: str, root: str, match_root: bool) -> bool:
    """Returns True iff `path` is contained in `root`.
    Returns `match_root` if `path` == `root`.
    """
    if not path.startswith(root):
      return False
    if len(path) == len(root):
      return match_root
    # Note - this prevents simple lexical failures such as
    #   "/a/bcdef" in "/a/b"
    # (both have the prefix "/a/b", but "/a/bcdef" is not contained in "/a/b")
    return path[len(root)] == self._path_mod.sep

  def add(self, path: str | config_types.Path, kind: FileType):
    """Marks the existence of `path`.

    This also implicitly marks all parent directories of `path` to also exist
    (as type DIRECTORY).
    """
    sPath: str = str(path)
    prev_path: str|None = None
    while sPath != prev_path:
      self._paths[sPath] = kind
      prev_path, sPath = sPath, self._path_mod.dirname(sPath)
      kind = FileType.DIRECTORY

  def copy(self, source: str | config_types.Path,
           dest: str | config_types.Path) -> None:
    """Copies the existence criteria of all known paths contained in `source` to `dest`.

    This also implicitly marks all parent directories of `path` to also exist
    (as type DIRECTORY).
    """
    source, dest = str(source), str(dest)
    to_add: dict[str, FileType] = {}
    for p in self._paths:
      if self._is_contained_in(p, source, match_root=True):
        to_add[p.replace(source, dest)] = self._paths[p]
    for path, kind in to_add.items():
      self.add(path, kind)

  def remove(self, path: str | config_types.Path, filt: Callable[[str],
                                                                 bool]) -> None:
    """Removes existence criteria for `path`, and any other paths it contains.

    `filt` is a required filter function. It will be called for each path
    contained in `path`, and if it returns True, the path will be removed from
    this path_set's existence list.
    """
    path = str(path)
    match_root: bool = True
    if path[-1] == self._path_mod.sep:
      match_root = False
      path = path.rstrip(self._path_mod.sep)
    kill_set: set[str] = set(
        p for p in self._paths
        if self._is_contained_in(p, path, match_root) and filt(p))
    for entry in kill_set:
      del self._paths[entry]

  def contains(self, path: str) -> bool:
    return path in self._paths

  def kind(self, path: str) -> FileType:
    return self._paths[path]


class fake_path:
  """Standin for os.path when we're in test mode.

  This class simulates the os.path interface exposed by PathApi, respecting the
  current platform according to the `platform` module. This allows us to
  simulate path functions according to the platform being tested, rather than
  the platform which is currently running.
  """

  def __init__(self, is_windows: bool,
               test_data: recipe_test_api.ModuleTestData):
    self._pth = ntpath if is_windows else posixpath
    self._mock_path_exists = path_set(self, test_data)

  def __getattr__(self, name: str) -> Any:
    return getattr(self._pth, name)

  def mock_add_paths(self, path: config_types.Path, kind: FileType) -> None:
    """Adds a path and all of its parents to the set of existing paths."""
    assert kind in FileType
    self._mock_path_exists.add(path, kind)

  def mock_copy_paths(self, source: str, dest: str) -> None:
    """Duplicates a path and all of its children to another path."""
    self._mock_path_exists.copy(source, dest)

  def mock_remove_paths(self, path: str, filt: Callable[[str], bool]) -> None:
    """Removes a path and all of its children from the set of existing paths."""
    self._mock_path_exists.remove(path, filt)

  # NOTE: These have `path: str` instead of config_types.Path because the
  # api._path_mod type is the intersection of (os.path && fake_path) - even if
  # these are strictly defined as config_types.Path, it will not enable better
  # type checking, because os.path is not defined in terms of
  # config_types.Path.

  def exists(self, path: str) -> bool:  # pylint: disable=method-hidden
    """Returns True if path refers to an existing path."""
    return self._mock_path_exists.contains(path)

  def isdir(self, path: str) -> bool:
    return self.exists(path) and self._mock_path_exists.kind(
        path) == FileType.DIRECTORY

  def isfile(self, path: str) -> bool:
    return self.exists(path) and self._mock_path_exists.kind(
        path) == FileType.FILE

  # This matches:
  #   [START_DIR]
  #   RECIPE[some_pkg::some_module:recipe_name]
  #
  # and friends at the beginning of a string.
  ROOT_MATCHER = re.compile(r'^[A-Z_]*\[[^]]*\]')

  def normpath(self, path: str) -> str:
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

  def abspath(self, path: str) -> str:
    """Returns the absolute version of path."""
    return self.normpath(path)

  def realpath(self, path: str) -> str:
    """Returns the canonical version of the path."""
    return self.normpath(path)


class PathApi(recipe_api.RecipeApi):
  _paths_client: recipe_api.PathsClient | recipe_api.UnresolvedRequirement = recipe_api.RequireClient(
      'paths')

  # This is the literal string 'checkout'.
  #
  # This is only being added as an intermediate step to removing the
  # dictionary-like API from the path module, and will be removed in the near
  # future. Do not use this.
  #
  # Use the .checkout_dir @property directly, instead.
  CheckoutPathName = 'checkout'

  # This is a frozenset of all the named base paths that this module knows
  # about.
  NamedBasePaths = frozenset([
      CheckoutPathName,
      'cache',
      'cleanup',
      'home',
      'start_dir',
      'tmp_base',
  ])

  def __init__(self, path_properties, **kwargs):
    super().__init__(**kwargs)

    self._start_dir: str
    self._temp_dir: str
    self._home_dir: str

    # These are populated in __init__ OR in initialize, but the rest of the
    # module will always see them as populated values.
    self._cleanup_dir: str = ""
    self._cache_dir: str = ""

    # checkout_dir can be set at most once per recipe run.
    self._checkout_dir: config_types.Path|None = None

    # Used in mkdtemp and mkstemp when generating and checking expectations.
    self._test_counter: collections.Counter = collections.Counter()

    if not self._test_data.enabled:  # pragma: no cover
      self._path_mod = os.path

      # HACK: config_types.Path._OS_SEP is a global variable.
      # This gets reset by config_types.ResetGlobalVariableAssignments()
      config_types.Path._OS_SEP = self._path_mod.sep

      for key in ('temp_dir', 'cache_dir', 'cleanup_dir'):
        value = path_properties.get(key)
        if value and not os.path.isabs(value):
          raise ValueError(
              f'Path {value!r} in path module property {key!r} is not absolute')

      # These we can compute without _paths_client.
      self._home_dir: str = self._path_mod.expanduser('~')
      self._temp_dir = path_properties.get('temp_dir', tempfile.gettempdir())

      # These MAY be provided via the module properties - if they are, set them
      # here, otherwise they will be populated in initialize().
      if cache_dir := path_properties.get('cache_dir'):
        self._cache_dir = cache_dir
      if cleanup_dir := path_properties.get('cleanup_dir'):
        self._cleanup_dir = cleanup_dir

    else:
      assert not isinstance(self._test_data, recipe_test_api.DisabledTestData)

      for key in ('temp_dir', 'cache_dir', 'cleanup_dir'):
        if value := path_properties.get(key):  # pragma: no cover
          raise ValueError(
              f'Base path mocking is not supported - got {key} = {value!r}')

      # HACK: The platform test_api sets platform.name specifically for the
      # path module when users use api.platform.name(...) in their tests.
      # This is dirty, but it avoids a LOT of interdependency complexity.
      _test_platform = self._test_data.get('platform.name', 'linux')

      self._cache_dir = '[CACHE]'
      self._cleanup_dir = '[CLEANUP]'
      self._home_dir = '[HOME]'
      self._start_dir = '[START_DIR]'
      self._temp_dir = '[TMP_BASE]'

      is_windows = _test_platform == 'win'

      # HACK: config_types.Path._OS_SEP is a global variable.
      # This gets reset by config_types.ResetGlobalVariableAssignments()
      config_types.Path._OS_SEP = '\\' if is_windows else '/'

      # NOTE: This depends on _OS_SEP being set.
      self._path_mod = fake_path(is_windows, self._test_data)

      self.mock_add_directory(self.cache_dir)
      self.mock_add_directory(self.cleanup_dir)
      self.mock_add_directory(self.home_dir)
      self.mock_add_directory(self.start_dir)
      self.mock_add_directory(self.tmp_base_dir)

  def initialize(self):
    """This is called by the recipe engine immediately after __init__(), but
    with `self._paths_client` initialized.
    """
    if not self._test_data.enabled:  # pragma: no cover
      # These paths can only be set with _paths_client, so we do them here in
      # initialize().

      self._start_dir = self._paths_client.start_dir
      if not self._cache_dir:
        self._cache_dir = os.path.join(self._start_dir, 'cache')

      # If no cleanup directory is specified, assume that any directory
      # underneath of the working directory is transient and will be purged in
      # between builds.
      if not self._cleanup_dir:
        self._cleanup_dir = os.path.join(self._start_dir, 'recipe_cleanup')

      self._ensure_dir(self._temp_dir)
      self._ensure_dir(self._cache_dir)
      self._ensure_dir(self._cleanup_dir)

  def _ensure_dir(self, path: str) -> None:  # pragma: no cover
    os.makedirs(path, exist_ok=True)

  def _split_path(self, path: str) -> tuple[str, ...]:  # pragma: no cover
    """Relative or absolute path -> tuple of components."""
    abs_path: list[str] = os.path.abspath(path).split(self.sep)
    # Guarantee that the first element is an absolute drive or the posix root.
    if abs_path[0].endswith(':'):
      abs_path[0] += '\\'
    elif abs_path[0] == '':
      abs_path[0] = '/'
    else:
      assert False, 'Got unexpected path format: %r' % abs_path
    return tuple(abs_path)

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
    assert isinstance(prefix, str), f'Prefix is not a string: {type(prefix)}'

    if not self._test_data.enabled:  # pragma: no cover
      cleanup_dir = str(self.cleanup_dir) + self.sep
      new_path = tempfile.mkdtemp(prefix=prefix, dir=cleanup_dir)
      assert new_path.startswith(cleanup_dir), (
          f'{new_path=!r} -- {cleanup_dir=!r}')
      temp_dir = self.cleanup_dir / new_path[len(cleanup_dir):]
    else:
      self._test_counter[prefix] += 1
      temp_dir = self.cleanup_dir / f'{prefix}_tmp_{self._test_counter[prefix]}'

    self.mock_add_paths(temp_dir, FileType.DIRECTORY)
    return temp_dir

  def mkstemp(self, prefix: str = tempfile.template) -> config_types.Path:
    """Makes a new temporary file, returns Path to it.

    Args:
      * prefix - a tempfile template for the file name (defaults to "tmp").

    Returns a Path to the new file.

    NOTE: Unlike tempfile.mkstemp, the file's file descriptor is closed. If you
    need the full security properties of mkstemp, please outsource this to e.g.
    either a resource script of your recipe module or recipe.
    """
    assert isinstance(prefix, str), f'Prefix is not a string: {type(prefix)}'

    if not self._test_data.enabled:  # pragma: no cover
      cleanup_dir = str(self.cleanup_dir) + self.sep
      fd, new_path = tempfile.mkstemp(prefix=prefix, dir=cleanup_dir)
      assert new_path.startswith(cleanup_dir), (
          f'{new_path=!r} -- {cleanup_dir=!r}')
      temp_file = self.cleanup_dir / new_path[len(cleanup_dir):]
      os.close(fd)
    else:
      self._test_counter[prefix] += 1
      temp_file = self.cleanup_dir.joinpath(
          f'{prefix}_tmp_{self._test_counter[prefix]}')
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
      * home_dir
      * start_dir
      * tmp_base_dir
      * cleanup_dir

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
      to_try = [
          self.cache_dir,
          self.checkout_dir,
          self.cleanup_dir,
          self.home_dir,
          self.start_dir,
          self.tmp_base_dir,
      ]
      for path in to_try:
        # checkout_dir can be None, skip it
        if path:
          sPath = str(path)
          if abs_string_path.startswith(sPath):
            break
      else:
        path = None

    if path is None or sPath is None:
      raise ValueError("could not figure out a base path for %r" %
                       abs_string_path)

    sub_path = abs_string_path[len(sPath):].strip(self.sep)
    return path.joinpath(*sub_path.split(self.sep))

  def __contains__(self, pathname: NamedBasePathsType) -> bool:
    """This method is DEPRECATED.

    If `pathname` is "checkout", returns True iff checkout_dir is set.
    If you want to check if checkout_dir is set, use
    `api.path.checkout_dir is not None` or similar, instead.

    Returns True for all other `pathname` values in NamedBasePaths.
    Returns False for all other values.

    In the past, the base paths that this module knew about were extensible via
    a very complicated 'config' system. All of that has been removed, but this
    method remains for now.
    """
    if pathname == self.CheckoutPathName:
      return bool(self.checkout_dir)
    return pathname in self.NamedBasePaths

  def __setitem__(self, pathname: CheckoutPathNameType,
                  path: config_types.Path) -> None:
    """Sets the checkout path.

    DEPRECATED - Assign directly to `api.path.checkout_dir` instead.

    The only valid value of `pathname` is the literal string CheckoutPathName.
    """
    if pathname != self.CheckoutPathName:
      raise ValueError(
          f'The only valid dynamic path value is `{self.CheckoutPathName}`. '
          f'Got {pathname!r}. Use `api.path.checkout_dir = <path>` instead.'
      )
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

    if isinstance(path.base, config_types.CheckoutBasePath):
      raise ValueError(
          f'api.path.checkout_dir cannot be rooted in checkout_dir: {path!r}')

    if (current := self._checkout_dir) is not None:
      if current == path:
        return

      raise ValueError(
          f'api.path.checkout_dir can only be set once. old:{current!r} new:{path!r}')

    self._checkout_dir = path
    # HACK: config_types.CheckoutBasePath._resolved is a global variable.
    # This gets reset by config_types.ResetGlobalVariableAssignments().
    config_types.CheckoutBasePath._resolved = path
    self.mock_add_directory(path)
    if self._test_data.enabled:
      assert isinstance(self._path_mod, fake_path)
      self._path_mod._mock_path_exists.mark_checkout_dir_set()

  def get(self, name: NamedBasePathsType) -> config_types.Path:
    """Gets the base path named `name`. See module docstring for more info.

    DEPRECATED: Use the following @properties on this module instead:
      * start_dir
      * tmp_base_dir
      * cache_dir
      * cleanup_dir
      * home_dir
      * checkout_dir (but use of checkout_dir is generally discouraged - just
      pass the Paths around instead of using this global variable).
    """
    match name:
      case 'cache':
        return self.cache_dir
      case 'checkout':
        if cdir := self.checkout_dir:
          # If the checkout_dir is already set, just return it directly.
          return cdir
        # In this case, the checkout_dir is not yet set, but it could be later.
        return config_types.Path(config_types.CheckoutBasePath())
      case 'cleanup':
        return self.cleanup_dir
      case 'home':
        return self.home_dir
      case 'start_dir':
        return self.start_dir
      case 'tmp_base':
        return self.tmp_base_dir

    raise ValueError(f'Unable to api.path.get({name!r}) - unknown base path.')

  def __getitem__(self, name: NamedBasePathsType) -> config_types.Path:
    """Gets the base path named `name`. See module docstring for more info.

    DEPRECATED: Use the following @properties on this module instead:
      * start_dir
      * tmp_base_dir
      * cache_dir
      * cleanup_dir
      * home_dir
      * checkout_dir (but use of checkout_dir is generally discouraged - just
      pass the Paths around instead of using this global variable).
    """
    self.m.warning.issue('PATH_GETITEM_DEPRECATED')
    return self.get(name)

  @property
  def start_dir(self) -> config_types.Path:
    """This is the directory that the recipe started in. it's similar to `cwd`,
    except that it's constant for the duration of the entire program.

    If you want to modify the current working directory for a set of steps,
    See the 'recipe_engine/context' module which allows modifying the cwd safely
    via a context manager.
    """
    return config_types.Path(config_types.ResolvedBasePath(self._start_dir))

  @property
  def home_dir(self) -> config_types.Path:
    """This is the path to the current $HOME directory.

    It is generally recommended to avoid using this, because it is an indicator
    that the recipe is non-hermetic.
    """
    return config_types.Path(config_types.ResolvedBasePath(self._home_dir))

  @property
  def tmp_base_dir(self) -> config_types.Path:
    """This directory is the system-configured temp dir.

    This is a weaker form of 'cleanup', and its use should be avoided. This may
    be removed in the future (or converted to an alias of 'cleanup').
    """
    return config_types.Path(config_types.ResolvedBasePath(self._temp_dir))

  @property
  def cache_dir(self) -> config_types.Path:
    """This directory is provided by whatever's running the recipe.

    When the recipe executes via Buildbucket, directories under here map to
    'named caches' which the Build has set. These caches would be preserved
    locally on the machine executing this recipe, and are restored for
    subsequent recipe exections on the same machine which request the same named
    cache.

    By default, Buildbucket installs a cache named 'builder' which is an
    immediate subdirectory of cache_dir, and will attempt to be persisted
    between executions of recipes on the same Buildbucket builder which use the
    same machine. So, if you are just looking for a place to put files which may
    be persisted between builds, use:

       api.path.cache_dir/'builder'

    As the base Path.

    Note that directories created under here /may/ be evicted in between runs of
    the recipe (i.e. to relieve disk pressure).
    """
    return config_types.Path(config_types.ResolvedBasePath(self._cache_dir))

  @property
  def cleanup_dir(self) -> config_types.Path:
    """This directory is guaranteed to be cleaned up (eventually) after the
    execution of this recipe.

    This directory is guaranteed to be empty when the recipe starts.
    """
    return config_types.Path(config_types.ResolvedBasePath(self._cleanup_dir))

  def cast_to_path(self, strpath: str) -> config_types.Path:
    """This returns a Path for strpath which can be used anywhere a Path is
    required.

    If `strpath` is not an absolute path (e.g. rooted with a valid Windows drive
    or a '/' for non-Windows paths), this will raise ValueError.

    This implicitly tries abs_to_path prior to returning a drive-rooted Path.
    This means that if strpath is a subdirectory of a known path (say,
    cache_dir), the returned Path will be based on that known path. This is
    important for test compatibility.
    """
    try:
      return self.abs_to_path(strpath)
    except ValueError:
      return _cast_to_path_impl(self._path_mod, strpath)

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
    api.path.start_dir) have a built-in join method (e.g.
    new_path = p.joinpath('some', 'name')). Many recipe modules expect Path
    objects rather than strings. Using this `join` method gives you raw path
    joining functionality and returns a string.

    If your path is rooted in one of the path module's root paths (i.e. those
    retrieved with api.path.something), then you can convert from a string path
    back to a Path with the `abs_to_path` method.
    """
    return self._path_mod.join(str(path), *[str(p) for p in paths])

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
    """Do not use this, use `api.path.home_dir` instead.

    This ONLY handles `path` == "~", and returns `str(api.path.home_dir)`.
    """
    if path == "~":
      return str(self.home_dir)
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
      assert isinstance(self._path_mod, fake_path)
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
      assert isinstance(self._path_mod, fake_path)
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

  def eq(self, path1: config_types.Path, path2: config_types.Path) -> bool:
    """Check whether path1 points to the same path as path2.

    DEPRECATED: Just directly compare path1 and path2 with `==`.
    """
    return path1 == path2

  def is_parent_of(self, parent: config_types.Path,
                   child: config_types.Path) -> bool:
    """Check whether child is contained within parent.

    DEPRECATED: Just use `parent.is_parent_of(child)`.
    """
    return parent.is_parent_of(child)
