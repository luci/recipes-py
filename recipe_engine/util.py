# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import functools
import os


SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))
BUILD_ROOT = os.path.dirname(os.path.dirname(SCRIPT_PATH))
ROOT_PATH = os.path.abspath(os.path.join(
  SCRIPT_PATH, os.pardir, os.pardir, os.pardir))
BASE_DIRS = [
  SCRIPT_PATH,
  os.path.join(ROOT_PATH, 'build_internal', 'scripts', 'slave'),
  os.path.join(ROOT_PATH, 'build_internal', 'scripts', 'slave-internal')
]
MODULE_DIRS = lambda: [os.path.join(x, 'recipe_modules') for x in BASE_DIRS]
RECIPE_DIRS = lambda: [os.path.join(x, 'recipes') for x in BASE_DIRS]

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
  return inner


def wrap_followup(kwargs, pre=False):
  """
  Decorator for a new followup_fn.

  Will pop the existing fn out of kwargs (if any), and return a decorator for
  the new folloup_fn.

  Args:
    kwargs - dictionary possibly containing folloup_fn
    pre - If true, the old folloup_fn is called before the wrapped function.
          Otherwise, the old followup_fn is called after the wrapped function.
  """
  null_fn = lambda _: None
  old_followup = kwargs.pop('followup_fn', null_fn)
  def decorator(f):
    @functools.wraps(f)
    def _inner(step_result):
      if pre:
        old_followup(step_result)
        f(step_result)
      else:
        f(step_result)
        old_followup(step_result)
    if old_followup is not null_fn:
      _inner.__name__ += '[%s]' % old_followup.__name__
    return _inner
  return decorator


