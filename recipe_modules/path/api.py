# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from slave import recipe_api


def path_method(api, name, base):
  """Returns aa shortcut static method which functions like os.path.join but
  with a fixed first component |base|.
  """
  def path_func_inner(*pieces, **kwargs):
    """Return a path to a file in '%s'.

    It supports the following kwargs:
      wrapper (bool): If true, the path should be considered to be a wrapper
                      script, and will gain the appropriate '.bat' extension
                      on windows.
    """
    use_wrapper = kwargs.get('wrapper') and api.m.platform.is_win
    WRAPPER_EXTENSION = '.bat' if use_wrapper else ''
    assert api.pardir not in pieces
    return api.join(base, *pieces) + WRAPPER_EXTENSION
  path_func_inner.__name__ = name
  path_func_inner.__doc__ = path_func_inner.__doc__ % base
  return path_func_inner


class mock_path(object):
  def __init__(self, api, _mock_path_exists):
    self._api = api
    self._mock_path_exists = set(_mock_path_exists)

  def exists(self, path):
    """Return True if path refers to an existing path."""
    return path in self._mock_path_exists

  def __getattr__(self, name):
    if self._api.platform.is_win:  # pragma: no cover
      import ntpath as pth
    elif self._api.platform.is_mac or self._api.platform.is_linux:
      import posixpath as pth
    return getattr(pth, name)


class PathApi(recipe_api.RecipeApi):
  """
  PathApi provides common os.path functions as well as convenience functions
  for generating absolute paths to things in a testable way.

  Mocks:
    exists (list): Paths which should exist in the test case. Thes must be paths
      using the [*_ROOT] placeholders. ex. '[BUILD_ROOT]/scripts'.
  """

  OK_METHODS = ('basename', 'abspath', 'join', 'pardir', 'exists', 'splitext')

  def __init__(self, **kwargs):
    super(PathApi, self).__init__(**kwargs)

    if self._mock is None:  # pragma: no cover
      self._path_mod = os.path
      # e.g. /b/build/slave/<slavename>/build
      self.slave_build = path_method(
        self, 'slave_build', self.abspath(os.getcwd()))

      # e.g. /b
      r = self.abspath(self.join(self.slave_build(), *([self.pardir]*4)))
      for token in ('build_internal', 'build', 'depot_tools'):
        # e.g. /b/{token}
        setattr(self, token, path_method(self, token, self.join(r, token)))
      self.root = path_method(self, 'root', r)
    else:
      self._path_mod = mock_path(self.m, self._mock.get('exists', []))
      self.slave_build = path_method(self, 'slave_build', '[SLAVE_BUILD_ROOT]')
      self.build_internal = path_method(
        self, 'build_internal', '[BUILD_INTERNAL_ROOT]')
      self.build = path_method(self, 'build', '[BUILD_ROOT]')
      self.depot_tools = path_method(self, 'depot_tools', '[DEPOT_TOOLS_ROOT]')
      self.root = path_method(self, 'root', '[ROOT]')

    # Because it only makes sense to call self.checkout() after
    # self.set_checkout() has been called, make calls to self.checkout()
    # explode with a helpful message until that point.
    def exploding_checkout_fn(*_pieces):  # pragma: no cover
      """Return a path to a file in '[SLAVE_BUILD_ROOT]/<checkout_dir>.'"""
      assert False, ('Cannot call path.checkout() '
                     'without calling path.set_checkout() first!')
    self.checkout = exploding_checkout_fn
    self.checkout_set = False

  def set_checkout(self, checkout_value):
    """Set <checkout_dir> for path.checkout()."""
    # TODO(iannucci): Make a better story than silently ignoring
    if not self.checkout_set:
      self.checkout = path_method(self, 'checkout', checkout_value)
      self.checkout_set = True

  def __getattr__(self, name):
    if name in self.OK_METHODS:
      return getattr(self._path_mod, name)
    raise AttributeError("'%s' object has no attribute '%s'" %
                         (self._path_mod, name))  # pragma: no cover

  def __dir__(self):  # pragma: no cover
    # Used for helping out show_me_the_modules.py
    return self.__dict__.keys() + list(self.OK_METHODS)

  # TODO(iannucci): Custom paths?
