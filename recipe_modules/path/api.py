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
  * `api.path['checkout']` - This directory is set by various 'checkout' modules
    in recipes. It was originally intended to make recipes easier to read and
    make code somewhat generic or homogeneous, but this was a mistake. New code
    should avoid 'checkout', and instead just explicitly pass paths around. This
    path may be removed in the future.

There are other anchor points which can be defined (e.g. by the
`depot_tools/infra_paths` module). Refer to those modules for additional
documentation.
"""

import collections
import itertools
import os
import re
import tempfile

from recipe_engine import recipe_api
from recipe_engine import config_types


FILE = 'FILE'
DIRECTORY = 'DIRECTORY'


class Error(Exception):
  """Error specific to path recipe module."""


def PathToString(api, test):

  def PathToString_inner(path):
    assert isinstance(path, config_types.Path)
    base_path = path.base.resolve(test.enabled)
    suffix = path.platform_ext.get(api.m.platform.name, '')
    return api.join(base_path, *path.pieces) + suffix

  return PathToString_inner


class path_set(object):
  """Implements a set which contains all the parents folders of added
  folders."""

  # TODO(iannucci): Expand this to be a full fakey filesystem, including file
  # contents and file types. Coordinate with the `file` module.
  def __init__(self, path_mod, initial_paths):
    self._path_mod = path_mod
    self._initial_paths = set(initial_paths)
    # An entry in self._paths means an object exists in the mock filesystem.
    # The value (either FILE or DIRECTORY) is the type of that object.
    self._paths = {}

  def _initialize(self):  # pylint: disable=method-hidden
    self._initialize = lambda: None
    for path in self._initial_paths:
      self.add(path, FILE)
    self._initial_paths = None
    self.contains = lambda path: path in self._paths

  @property
  def _separator(self):
    return self._path_mod.sep

  def _is_contained_in(self, path, root, match_root):
    if not path.startswith(root):
      return False
    if len(path) == len(root):
      return match_root
    return path[len(root)] == self._separator

  def add(self, path, kind):
    path = str(path)
    self._initialize()
    prev_path = None
    while path != prev_path:
      self._paths[path] = kind
      prev_path, path = path, self._path_mod.dirname(path)
      kind = DIRECTORY

  def copy(self, source, dest):
    source, dest = str(source), str(dest)
    self._initialize()
    to_add = {}
    for p in self._paths:
      if self._is_contained_in(p, source, match_root=True):
        to_add[p.replace(source, dest)] = self._paths[p]
    for path, kind in to_add.iteritems():
      self.add(path, kind)

  def remove(self, path, filt):
    path = str(path)
    self._initialize()
    match_root = True
    if path[-1] == self._separator:
      match_root = False
      path = path.rstrip(self._separator)
    kill_set = set(
        p for p in self._paths
        if self._is_contained_in(p, path, match_root) and filt(p))
    for entry in kill_set:
      del self._paths[entry]

  def contains(self, path):  # pylint: disable=method-hidden
    self._initialize()
    return self.contains(path)

  def kind(self, path):
    self._initialize()
    return self._paths[path]


class fake_path(object):
  """Standin for os.path when we're in test mode.

  This class simulates the os.path interface exposed by PathApi, respecting the
  current platform according to the `platform` module. This allows us to
  simulate path functions according to the platform being tested, rather than
  the platform which is currently running.
  """

  def __init__(self, api, _mock_path_exists):
    self._api = api
    self._mock_path_exists = path_set(self, _mock_path_exists)
    self._pth = None

  def _init_pth(self):
    if not self._pth:
      if self._api.m.platform.is_win:
        import ntpath as pth
      elif self._api.m.platform.is_mac or self._api.m.platform.is_linux:
        import posixpath as pth
      self._pth = pth

  def __getattr__(self, name):
    self._init_pth()
    return getattr(self._pth, name)

  def mock_add_paths(self, path, kind):
    """Adds a path and all of its parents to the set of existing paths."""
    self._mock_path_exists.add(path, kind)

  def mock_copy_paths(self, source, dest):
    """Duplicates a path and all of its children to another path."""
    self._mock_path_exists.copy(source, dest)

  def mock_remove_paths(self, path, filt):
    """Removes a path and all of its children from the set of existing paths."""
    self._mock_path_exists.remove(path, filt)

  def exists(self, path):  # pylint: disable=E0202
    """Returns True if path refers to an existing path."""
    return self._mock_path_exists.contains(path)

  def isdir(self, path):
    return self.exists(path) and self._mock_path_exists.kind(path) == DIRECTORY

  def isfile(self, path):
    return self.exists(path) and self._mock_path_exists.kind(path) == FILE

  # This matches:
  #   [START_DIR]
  #   RECIPE[some_pkg::some_module:recipe_name]
  #
  # and friends at the beginning of a string.
  ROOT_MATCHER = re.compile(r'^[A-Z_]*\[[^]]*\]')

  def normpath(self, path):
    """Normalizes the path.

    This splits off a recipe base (i.e. RECIPE[...]) so that normpath is
    only called on the user-supplied portion of the path.
    """
    self._init_pth()
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

  def abspath(self, path):
    """Returns the absolute version of path."""
    return self.normpath(path)

  def realpath(self, path):
    """Returns the canonical version of the path."""
    return self.normpath(path)


class PathApi(recipe_api.RecipeApi):
  _paths_client = recipe_api.RequireClient('paths')

  def get_config_defaults(self):
    """Internal recipe implementation function."""
    return {
        # Needed downstream in depot_tools
        'PLATFORM': self.m.platform.name,
        'START_DIR': self._startup_cwd,
        'TEMP_DIR': self._temp_dir,
        'CACHE_DIR': self._cache_dir,
        'CLEANUP_DIR': self._cleanup_dir,
        'HOME_DIR': self._home_dir,
    }

  def __init__(self, path_properties, **kwargs):
    super(PathApi, self).__init__(**kwargs)
    config_types.Path.set_tostring_fn(PathToString(self, self._test_data))
    config_types.NamedBasePath.set_path_api(self)

    self._path_properties = path_properties

    # Assigned at "initialize".
    self._path_mod = None  # NT or POSIX path module, or "os.path" in prod.
    self._startup_cwd = None
    self._temp_dir = None
    self._cache_dir = None
    self._cleanup_dir = None
    self._home_dir = None

    # Used in mkdtemp and mkstemp when generating and checking expectations.
    self._test_counter = collections.Counter()

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

  def _ensure_dir(self, path):  # pragma: no cover
    try:
      os.makedirs(path)
    except os.error:
      pass  # Perhaps already exists.

  def _split_path(self, path):  # pragma: no cover
    """Relative or absolute path -> tuple of components."""
    abs_path = os.path.abspath(path).split(self.sep)
    # Guarantee that the first element is an absolute drive or the posix root.
    if abs_path[0].endswith(':'):
      abs_path[0] += '\\'
    elif abs_path[0] == '':
      abs_path[0] = '/'
    else:
      assert False, 'Got unexpected path format: %r' % abs_path
    return abs_path

  def initialize(self):
    """Internal recipe implementation function."""
    if not self._test_data.enabled:  # pragma: no cover
      self._path_mod = os.path
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
      self._path_mod = fake_path(self, self._test_data.get('exists', []))

      root = 'C:\\' if self.m.platform.is_win else '/'
      self._startup_cwd = [root, 'b', 'FakeTestingCWD']
      # Appended to placeholder '[TMP]' to get fake path in test.
      self._temp_dir = [root]
      self._cache_dir = [root, 'b', 'c']
      self._cleanup_dir = [root, 'b', 'cleanup']
      self._home_dir = [root, 'home', 'fake_user']

    self.set_config('BASE')

  def assert_absolute(self, path):
    """Raises AssertionError if the given path is not an absolute path.

    Args:
      * path (Path|str) - The path to check.
    """
    if self.abspath(path) != str(path):
      raise AssertionError('%s is not absolute' % path)

  def mkdtemp(self, prefix=tempfile.template):
    """Makes a new temporary directory, returns Path to it.

    Args:
      * prefix (str) - a tempfile template for the directory name (defaults
        to "tmp").

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
      assert isinstance(prefix, basestring)
      temp_dir = self['cleanup'].join('%s_tmp_%d' %
                                      (prefix, self._test_counter[prefix]))
    self.mock_add_paths(temp_dir, DIRECTORY)
    return temp_dir

  def mkstemp(self, prefix=tempfile.template):
    """Makes a new temporary file, returns Path to it.

    Args:
      * prefix (str) - a tempfile template for the file name (defaults to
        "tmp").

    Returns a Path to the new file. Unlike tempfile.mkstemp, the file's file
    descriptor is closed.
    """
    if not self._test_data.enabled:  # pragma: no cover
      # New path as str.
      fd, new_path = tempfile.mkstemp(prefix=prefix, dir=str(self['cleanup']))
      # Ensure it's under self._cleanup_dir, convert to Path.
      new_path = self._split_path(new_path)
      assert new_path[:len(self._cleanup_dir)] == self._cleanup_dir, (
          'new_path: %r -- cleanup_dir: %r' % (new_path, self._cleanup_dir))
      temp_file = self['cleanup'].join(*new_path[len(self._cleanup_dir):])
      os.close(fd)
    else:
      self._test_counter[prefix] += 1
      assert isinstance(prefix, basestring)
      temp_file = self['cleanup'].join('%s_tmp_%d' %
                                       (prefix, self._test_counter[prefix]))
    self.mock_add_paths(temp_file, FILE)
    return temp_file

  def abs_to_path(self, abs_string_path):
    """Converts an absolute path string `string_path` to a real Path object,
    using the most appropriate known base path.

      * abs_string_path MUST be an absolute path
      * abs_string_path MUST be rooted in one of the configured base paths known
        to the path module.

    This method will find the longest match in all the following:
      * module resource paths
      * recipe resource paths
      * repo paths
      * dynamic_paths
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
    ap = self.abspath(abs_string_path)
    if ap != abs_string_path:
      raise ValueError("path is not absolute: %r v %r" % (abs_string_path, ap))

    # try module/recipe/repo resource paths first
    sPath, path = self._paths_client.find_longest_prefix(
        abs_string_path, self.sep)
    if path is None:
      # try base paths now
      for path_name in itertools.chain(self.c.dynamic_paths, self.c.base_paths):
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

  def __contains__(self, pathname):
    return any(
        path_set.get(pathname)
        for path_set in (self.c.dynamic_paths, self.c.base_paths))

  def __setitem__(self, pathname, path):
    assert isinstance(path, config_types.Path), (
        'Setting dynamic path to something other than a Path: %r' % path)
    assert pathname in self.c.dynamic_paths, (
        'Must declare dynamic path (%r) in config before setting it.' % path)
    assert isinstance(path.base, config_types.BasePath), (
        'Dynamic path values must be based on a base_path' % path.base)
    self.c.dynamic_paths[pathname] = path

  def get(self, name, default=None):
    """Gets the base path named `name`. See module docstring for more
    information."""
    if name in self.c.base_paths or name in self.c.dynamic_paths:
      return config_types.Path(config_types.NamedBasePath(name))
    return default

  def __getitem__(self, name):
    """Gets the base path named `name`. See module docstring for more
    information."""
    result = self.get(name)
    if not result:
      raise KeyError('Unknown path: %s' % name)
    return result

  @property
  def pardir(self):
    """Equivalent to os.path.pardir."""
    return self._path_mod.pardir

  @property
  def sep(self):
    """Equivalent to os.path.sep."""
    return self._path_mod.sep

  @property
  def pathsep(self):
    """Equivalent to os.path.pathsep."""
    return self._path_mod.pathsep

  def abspath(self, path):
    """Equivalent to os.path.abspath."""
    return self._path_mod.abspath(str(path))

  def basename(self, path):
    """Equivalent to os.path.basename."""
    return self._path_mod.basename(str(path))

  def dirname(self, path):
    """Equivalent to os.path.dirname."""
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
    """Equivalent to os.path.split."""
    return self._path_mod.split(str(path))

  def splitext(self, path):
    """Equivalent to os.path.splitext."""
    return self._path_mod.splitext(str(path))

  def realpath(self, path):
    """Equivalent to os.path.realpath."""
    return self._path_mod.realpath(str(path))

  def relpath(self, path, start):
    """Roughly equivalent to os.path.relpath.

    Unlike os.path.relpath, `start` is _required_. If you want the 'current
    directory', use the `recipe_engine/context` module's `cwd` property.
    """
    return self._path_mod.relpath(str(path), str(start))

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

  def mock_add_paths(self, path, kind=FILE):
    """For testing purposes, mark that |path| exists."""
    if self._test_data.enabled:
      self._path_mod.mock_add_paths(path, kind)

  def mock_add_file(self, path):
    """For testing purposes, mark that file |path| exists."""
    self.mock_add_paths(path, FILE)

  def mock_add_directory(self, path):
    """For testing purposes, mark that directory |path| exists."""
    self.mock_add_paths(path, DIRECTORY)

  def mock_copy_paths(self, source, dest):
    """For testing purposes, copy |source| to |dest|."""
    if self._test_data.enabled:
      self._path_mod.mock_copy_paths(source, dest)

  def mock_remove_paths(self, path, filt=lambda p: True):
    """For testing purposes, assert that |path| doesn't exist.

    Args:
      * path (str|Path): The path to remove.
      * filt (func[str] bool): Called for every candidate path. Return
        True to remove this path.
    """
    if self._test_data.enabled:
      self._path_mod.mock_remove_paths(path, filt)
