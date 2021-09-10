# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from io import StringIO

import contextlib
import datetime
import functools
import logging
import os
import sys
import time
import traceback

from builtins import map, range
from builtins import str as text
from future.utils import iteritems
from past.builtins import basestring


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
    if self.owner_module is None:
      raise ModuleInjectionError(
        "RecipeApi has no dependency %r. (Add it to DEPS?)" % (key,))
    else:
      raise ModuleInjectionError(
        "Recipe Module %r has no dependency %r. (Add it to __init__.py:DEPS?)"
        % (self.owner_module.name, key))


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


def _returns_placeholder(func, alternate_name=None):
  @static_wraps(func)
  def inner(self, *args, **kwargs):
    ret = static_call(self, func, *args, **kwargs)
    assert isinstance(ret, Placeholder)
    ret.namespaces = (self.name, alternate_name or static_name(self, func))
    return ret
  # prevent this placeholder-returning function from becoming a composite_step.
  inner._non_step = True # pylint: disable=protected-access
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
        self.lines[-1].write(text(s))
        break
      self.lines[-1].write(text(s[:i]))
      self.lines[-1] = self.lines[-1].getvalue()
      self.lines.append(StringIO())
      s = s[i+1:]

  def close(self):
    if isinstance(self.lines[-1], StringIO):
      self.lines[-1] = self.lines[-1].getvalue()


class exponential_retry(object):
  """Decorator which retries the function if an exception is encountered."""

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
          time.sleep(retry_delay.total_seconds())
          retry_delay *= 2
    return wrapper


class MultiException(Exception):
  """An exception that aggregates multiple exceptions and summarizes them."""

  class Builder(object):
    """Iteratively constructs a MultiException."""

    def __init__(self):
      self._exceptions = []

    def append(self, exc):
      if exc is not None:
        self._exceptions.append(exc)

    def get(self):
      """Returns (MultiException or None): The constructed MultiException.

      If no exceptions have been appended, None will be returned.
      """
      return MultiException(*self._exceptions) if self._exceptions else (None)

    def raise_if_any(self):
      mexc = self.get()
      if mexc is not None:
        raise mexc

    @contextlib.contextmanager
    def catch(self, *exc_types):
      """ContextManager that catches any exception raised during its execution
      and adds them to the MultiException.

      Args:
        exc_types (list): A list of exception classes to catch. If empty,
            Exception will be used.
      """
      exc_types = exc_types or (Exception,)
      try:
        yield
      except exc_types as exc:
        self.append(exc)


  def __init__(self, *base):
    super(MultiException, self).__init__()

    # Determine base Exception text.
    if len(base) == 0:
      self.message = 'No exceptions'
    elif len(base) == 1:
      self.message = str(base[0])
    else:
      self.message = str(base[0]) + ', and %d more...' % (len(base)-1)
    self._inner = base

  def __bool__(self):
    return bool(self._inner)

  __nonzero__ = __bool__ # py2 compatibility

  def __len__(self):
    return len(self._inner)

  def __getitem__(self, key):
    return self._inner[key]

  def __iter__(self):
    return iter(self._inner)

  def __str__(self):
    return '%s(%s)' % (type(self).__name__, self.message)


@contextlib.contextmanager
def map_defer_exceptions(fn, it, *exc_types):
  """Executes "fn" for each element in "it". Any exceptions thrown by "fn" will
  be deferred until the end of "it", then raised as a single MultiException.

  Args:
    fn (callable): A function to call for each element in "it".
    it (iterable): An iterable to traverse.
    exc_types (list): An optional list of specific exception types to defer.
        If empty, Exception will be used. Any Exceptions not referenced by this
        list will skip deferring and be immediately raised.
  """
  mexc_builder = MultiException.Builder()
  for e in it:
    with mexc_builder.catch(*exc_types):
      fn(e)
  mexc_builder.raise_if_any()


MIN_SAFE_INTEGER = -((2**53) - 1)
MAX_SAFE_INTEGER = (2**53) - 1

def fix_json_object(obj):
  """Recursively:

    * Re-encodes strings as utf-8 inside |obj| (python2 only).
    * Replaces floats with ints when:
      * The value is a whole number
      * The value is outside of [-(2 ** 53 - 1), 2 ** 53 - 1]

  Returns the result.
  """
  if sys.version_info.major == 2 and isinstance(obj, unicode):
    return obj.encode('utf-8', 'replace')

  if isinstance(obj, list):
    return list(map(fix_json_object, obj))

  if isinstance(obj, float):
    if obj.is_integer() and (MIN_SAFE_INTEGER <= obj <= MAX_SAFE_INTEGER):
      return int(obj)
    return obj

  if isinstance(obj, dict):
    new_obj = type(obj)(
        (fix_json_object(k), fix_json_object(v)) for k, v in iteritems(obj))
    return new_obj

  return obj


_FULL_STACKS = True
_RECIPE_ENGINE_BASE = os.path.dirname(__file__)

def enable_filtered_stacks():
  """Sets an internal option to filter engine implementation details out of
  stack traces.

  Only set during tests when '--full-stacks' is not specified.
  """
  global _FULL_STACKS
  _FULL_STACKS = False


def remove_engine_impl_from_stack(stack):
  """Takes a 'processed' stack (e.g. from traceback.extract_stack) and removes
  recipe engine implementation frames (i.e. not from recipes or recipe modules).
  This filtering starts in the stack at the first "non-engine" code; This means
  that if the engine code DOES crash, the full stack will be shown anyway, and
  if the exception originates from inside the engine code, these frames will be
  shown as well.

  This will also trim frames which are from known third-party libraries (like
  gevent).

  Is a NO-OP unless enable_filtered_stacks() has been called.
  """
  if _FULL_STACKS:
    return stack

  def _is_engine_impl(frame):
    return (
      frame[0].startswith(_RECIPE_ENGINE_BASE) or
      frame[2].startswith('gevent.')
    )

  # stack is organized from deep->shallow. We process the stack backwards; We
  # walk until we find some `not _is_engine_impl` frame, and then above that we
  # filter all `_is_engine_impl` frames.
  ret = []
  found_user_code = False
  for frame in reversed(stack):
    is_engine = _is_engine_impl(frame)
    if found_user_code and is_engine:
      continue
    ret.append(frame)
    found_user_code = found_user_code or (not is_engine)

  return list(reversed(ret))


def extract_tb(tb):
  """Return a 'processed' stack (as from traceback.extract_tb).

  If enable_filtered_stacks() was called, this trims the stack per
  remove_engine_impl_from_stack.
  """
  return remove_engine_impl_from_stack(traceback.extract_tb(tb))


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
  return "%s(%s)" % (type(ex).__name__,
                     ', '.join("'%s'" % str(arg) for arg in ex.args))