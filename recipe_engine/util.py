# Copyright 2013-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import os

from cStringIO import StringIO

class RecipeAbort(Exception):
  pass


class ModuleInjectionError(AttributeError):
  pass


class ModuleInjectionSite(object):
  def __init__(self, owner_module=None):
    self.owner_module = owner_module

  def __getattr__(self, key):
    if self.owner_module is None:
      raise ModuleInjectionError(
        "RecipeApi has no dependency %r. (Add it to DEPS?)" % (key,))
    else:
      raise ModuleInjectionError(
        "Recipe Module %r has no dependency %r. (Add it to __init__.py:DEPS?)"
        % (self.owner_module.name, key))


class Placeholder(object):
  """Base class for json placeholders. Do not use directly."""
  def __init__(self):
    self.name_pieces = None

  @property
  def backing_file(self):  # pragma: no cover
    """Return path to a temp file that holds or receives the data.

    Valid only after 'render' has been called.
    """
    raise NotImplementedError

  def render(self, test):  # pragma: no cover
    """Return [cmd items]*"""
    raise NotImplementedError

  def result(self, presentation, test):
    """Called after step completion.

    Args:
      presentation (StepPresentation) - for the current step.
      test (PlaceholderTestData) - test data for this placeholder.

    Returns value to add to step result.

    May optionally modify presentation as a side-effect.
    """
    pass

  @property
  def name(self):
    assert self.name_pieces
    return "%s.%s" % self.name_pieces


def static_wraps(func):
  wrapped_fn = func
  if isinstance(func, staticmethod):
    # __get__(obj) is the way to get the function contained in the staticmethod.
    # python 2.7+ has a __func__ member, but previous to this the attribute
    # doesn't exist. It doesn't matter what the obj is, as long as it's not
    # None.
    wrapped_fn = func.__get__(object)
  return functools.wraps(wrapped_fn)


def static_call(obj, func, *args, **kwargs):
  if isinstance(func, staticmethod):
    return func.__get__(obj)(*args, **kwargs)
  else:
    return func(obj, *args, **kwargs)


def static_name(obj, func):
  if isinstance(func, staticmethod):
    return func.__get__(obj).__name__
  else:
    return func.__name__


def returns_placeholder(func):
  @static_wraps(func)
  def inner(self, *args, **kwargs):
    ret = static_call(self, func, *args, **kwargs)
    assert isinstance(ret, Placeholder)
    ret.name_pieces = (self.name, static_name(self, func))
    return ret
  # prevent this placeholder-returning function from becoming a composite_step.
  inner._non_step = True # pylint: disable=protected-access
  return inner


def cached_unary(f):
  """Decorator that caches/memoizes an unary function result.

  If the function throws an exception, the cache table will not be updated.
  """
  cache = {}
  empty = object()

  @functools.wraps(f)
  def cached_f(inp):
    cache_entry = cache.get(inp, empty)
    if cache_entry is empty:
      cache_entry = f(inp)
      cache[inp] = cache_entry
    return cache_entry
  return cached_f


def scan_directory(path, predicate):
  """Recursively scans a directory and yields paths that match predicate."""
  for root, _dirs, files in os.walk(path):
    for file_name in (f for f in files if predicate(f)):
      file_path = os.path.join(root, file_name)
      yield file_path


class StringListIO(object):
  def __init__(self):
    self.lines = [StringIO()]

  def write(self, s):
    while s:
      i = s.find('\n')
      if i == -1:
        self.lines[-1].write(s)
        break
      self.lines[-1].write(s[:i])
      self.lines[-1] = self.lines[-1].getvalue()
      self.lines.append(StringIO())
      s = s[i+1:]

  def close(self):
    if not isinstance(self.lines[-1], basestring):
      self.lines[-1] = self.lines[-1].getvalue()
