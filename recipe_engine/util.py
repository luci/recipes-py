# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from io import StringIO

import contextlib
import datetime
import functools
import logging
import os
import re
import sys
import gevent
import traceback

import six

from builtins import map, range
from past.builtins import basestring
from recipe_engine.internal.global_shutdown import GLOBAL_SHUTDOWN


def sentinel(name, **attrs):
  """Create a sentinel object.

  The sentinel's type is a class with the given name that has no behavior except
  that it's string representation is also the given name. The sentinel is
  intended for use where some special behavior is required where there is no
  acceptable special value in the type of an argument. An identity check (x is
  SENTINEL) can be used to check for the sentinel.

  Any additional attributes can be passed via `attrs`. This can be useful to
  associate metadata with the sentinel object.
  """
  all_attrs = dict(attrs)
  all_attrs.update({
      '__repr__': lambda _: name,
      '__copy__': lambda self: self,
      '__deepcopy__': lambda self, _: self,
  })
  return type(name, (), all_attrs)()


class RecipeAbort(Exception):
  pass


class ModuleInjectionError(AttributeError):
  pass


class ModuleInjectionSite(object):
  def __init__(self, owner_module=None):
    self.owner_module = owner_module

  def __getattr__(self, key):
    raise ModuleInjectionError(
      "Recipe Module %r has no dependency %r. (Add it to __init__.py:DEPS?)"
      % (module_name(self.owner_module), key))


class Placeholder(object):
  """Base class for command line argument placeholders. Do not use directly."""
  def __init__(self, name=None):
    if name is not None:
      assert isinstance(name, basestring), (
          'Expect a string name for a placeholder, but got %r' % name)
    self.name = name
    self.namespaces = None

  @property
  def backing_file(self):  # pragma: no cover
    """Return path to a temp file that holds or receives the data.

    Valid only after 'render' has been called.
    """
    raise NotImplementedError

  def render(self, test):  # pragma: no cover
    """Return [cmd items]*"""
    raise NotImplementedError

  @property
  def label(self):
    if self.name is None:
      return "%s.%s" % self.namespaces
    else:
      return "%s.%s[%s]" % (self.namespaces[0], self.namespaces[1], self.name)


class InputPlaceholder(Placeholder):
  """Base class for json/raw_io input placeholders. Do not use directly."""
  def cleanup(self, test_enabled):
    """Called after step completion.

    Args:
      test_enabled (bool) - indicate whether running in simulation mode.
    """
    pass


class OutputPlaceholder(Placeholder):
  """Base class for json/raw_io output placeholders. Do not use directly."""
  def result(self, presentation, test):
    """Called after step completion.

    Args:
      presentation (StepPresentation) - for the current step.
      test (PlaceholderTestData) - test data for this placeholder.

    May optionally modify presentation as a side-effect.
    Returned value will be added to the step result.
    """
    pass


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


_modname_re = re.compile(r'RECIPE_MODULES\.[^.]*\.([^.]*)\..*')

def module_name(api_subclass_instance: object) -> str:
  py_mod_name = api_subclass_instance.__class__.__module__
  if m := _modname_re.match(py_mod_name):
    return m.group(1)
  raise ValueError(f'Cannot find recipe module name from {py_mod_name}')


def _returns_placeholder(func, alternate_name=None):
  @static_wraps(func)
  def inner(self, *args, **kwargs):
    ret = static_call(self, func, *args, **kwargs)
    assert isinstance(ret, Placeholder)
    selfname = module_name(self)
    ret.namespaces = (selfname, alternate_name or static_name(self, func))
    return ret
  # prevent this placeholder-returning function from becoming a composite_step.
  return inner

def returns_placeholder(func):
  """Decorates a RecipeApi placeholder-returning method to set the namespace
  of the returned PlaceHolder.

  The default namespace will be a tuple of (RECIPE_MODULE_NAME, method_name).
  You can also decorate the method by `@returns_placeholder(alternate_name)` so
  that the placeholder will have namespace (RECIPE_MODULE_NAME, alternate_name).
  """
  if callable(func) or isinstance(func, staticmethod):
    return _returns_placeholder(func)
  elif isinstance(func, str) and func:
    def decorator(f):
      return _returns_placeholder(f, func)
    return decorator
  else:
    raise ValueError('Expected either a function or string; got %r' % func)

class StringListIO(object):
  def __init__(self):
    self.lines = [StringIO()]

  def write(self, s):
    while s:
      i = s.find('\n')
      if i == -1:
        self.lines[-1].write(str(s))
        break
      self.lines[-1].write(str(s[:i]))
      self.lines[-1] = self.lines[-1].getvalue()
      self.lines.append(StringIO())
      s = s[i+1:]

  def close(self):
    if isinstance(self.lines[-1], StringIO):
      self.lines[-1] = self.lines[-1].getvalue()


class exponential_retry(object):
  """Decorator which retries the function if an exception is encountered.

  THIS FUNCTION IS DEPRECATED.Use the 'time' recipe module's version of this
  instead.

  TODO(iannucci): Use a recipe warning for this
  """

  def __init__(self, retries=None, delay=None, condition=None):
    """Creates a new exponential retry decorator.

    Args:
      retries (int): Maximum number of retries before giving up.
      delay (datetime.timedelta): Amount of time to wait before retrying. This
          will double every retry attempt (exponential).
      condition (func): If not None, a function that will be passed the
          exception as its one argument. Retries will only happen if this
          function returns True. If None, retries will always happen.
    """
    self.retries = retries or 5
    self.delay = delay or datetime.timedelta(seconds=1)
    self.condition = condition or (lambda e: True)

  def __call__(self, f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
      retry_delay = self.delay
      for i in range(self.retries):
        try:
          return f(*args, **kwargs)
        except Exception as e:
          if (i+1) >= self.retries or not self.condition(e):
            raise
          logging.exception('Exception encountered, retrying in %s',
                            retry_delay)
          gevent.wait([GLOBAL_SHUTDOWN], timeout=retry_delay.total_seconds())
          retry_delay *= 2
    return wrapper


MIN_SAFE_INTEGER = -((2**53) - 1)
MAX_SAFE_INTEGER = (2**53) - 1

def fix_json_object(obj):
  """Recursively:

    * Replaces floats with ints when:
      * The value is a whole number
      * The value is outside of [-(2 ** 53 - 1), 2 ** 53 - 1]

  Returns the result.
  """
  if sys.version_info.major == 2 and isinstance(obj, six.text_type):
    return obj.encode('utf-8', 'replace')

  if isinstance(obj, list):
    return list(map(fix_json_object, obj))

  if isinstance(obj, float):
    if obj.is_integer() and (MIN_SAFE_INTEGER <= obj <= MAX_SAFE_INTEGER):
      return int(obj)
    return obj

  if isinstance(obj, dict):
    new_obj = type(obj)(
        (fix_json_object(k), fix_json_object(v)) for k, v in obj.items())
    return new_obj

  return obj


# Convert some known py3 err msg to py2 err msg, otherwise, convert to a
# constant err msg.
# TODO(crbug.com/1147793): remove it after py3 migration is done.
def unify_json_load_err(err):
  py2_err = 'No JSON object could be decoded'
  if (err.startswith('Expecting property name') or
      err.startswith('Expecting value')):
    return py2_err
  return py2_err if err.startswith(py2_err) else 'Wrong JSON object format'


def format_ex(ex):
  """Return the same format of string representation for Exception objects in
  both python2 and python3.
  """
  return "%s(%s)" % (type(ex).__name__, ', '.join(
      "'%s'" % str(arg) for arg in ex.args))
