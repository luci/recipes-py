# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib
import datetime
import functools
import itertools
import logging
import os
import sys
import time
import traceback
import urllib

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


def returns_placeholder(func):
  @static_wraps(func)
  def inner(self, *args, **kwargs):
    ret = static_call(self, func, *args, **kwargs)
    assert isinstance(ret, Placeholder)
    ret.namespaces = (self.name, static_name(self, func))
    return ret
  # prevent this placeholder-returning function from becoming a composite_step.
  inner._non_step = True # pylint: disable=protected-access
  return inner


BUG_LINK = (
    'https://code.google.com/p/chromium/issues/entry?%s' % urllib.urlencode({
        'summary': 'Recipe engine bug: unexpected failure',
        'comment': 'Link to the failing build and paste the exception here',
        'labels': 'Infra,Infra-Area-Recipes,Pri-1,Restrict-View-Google,'
                  'Infra-Troopers',
        'cc': 'martiniss@chromium.org,iannucci@chromium.org',
    }))


@contextlib.contextmanager
def raises(exc_cls, stream_engine=None):
  """If the body raises an exception not in exc_cls, print and abort the engine.

  This is so that we have something to go on when a function goes wrong, yet the
  exception is covered up by something else (e.g. an error in a finally block).
  """

  try:
    yield
  except Exception as e:
    if isinstance(e, exc_cls):
      raise
    else:
      # Print right away in case the bug is in the stream_engine.
      traceback.print_exc()
      print '@@@STEP_EXCEPTION@@@'

      if stream_engine:
        # Now do it a little nicer with annotations.
        with stream_engine.make_step_stream('Recipe engine bug') as stream:
          stream.set_step_status('EXCEPTION')
          with stream.new_log_stream('exception') as log:
            log.write_split(traceback.format_exc())
          stream.add_step_link('file a bug', BUG_LINK)
      sys.stdout.flush()
      sys.stderr.flush()
      os._exit(2)


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
      for i in xrange(self.retries):
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

  def __nonzero__(self):
    return bool(self._inner)

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


def strip_unicode(obj):
  """Recursively re-encodes strings as utf-8 inside |obj|. Returns the result.
  """
  if isinstance(obj, unicode):
    return obj.encode('utf-8', 'replace')

  if isinstance(obj, list):
    return map(strip_unicode, obj)

  if isinstance(obj, dict):
    new_obj = type(obj)(
        (strip_unicode(k), strip_unicode(v)) for k, v in obj.iteritems() )
    return new_obj

  return obj


if sys.platform == "win32":
  _hunt_path_exts = ('.exe', '.bat')
  def hunt_path(cmd0, env):
    """This takes the lazy cross-product of PATH and ('.exe', '.bat') to find
    what cmd.exe would have found for the command if we used shell=True.

    This must be called with the output from _merge_envs to pick up any changes
    to PATH.

    If it succeeds, it returns a new cmd0. If it fails, it returns the
    same cmd0, and subprocess will run as normal (and likely fail).

    This will not attempt to do any evaluations for commands where the program
    already has an explicit extension (.exe, .bat, etc.), and it will not
    attempt to do any evaluations for commands where the program is an absolute
    path.

    This DOES NOT use PATHEXT to keep the recipe engine's behavior as
    predictable as possible. We don't currently rely on any other runnable
    extensions besides these two, and when we could, we choose to explicitly
    invoke the interpreter (e.g. python.exe, cscript.exe, etc.).
    """
    if '.' in cmd0:  # something.ext will work fine with subprocess.
      return cmd0
    if os.path.isabs(cmd0):  # PATH isn't even used
      return cmd0

    # begin the hunt
    paths = env.get('PATH', '').split(os.pathsep)
    if not paths:
      return cmd0

    # try every extension for each path
    for path, ext in itertools.product(paths, _hunt_path_exts):
      candidate = os.path.join(path, cmd0+ext)
      if os.path.isfile(candidate):
        return candidate
    return cmd0
else:
  def hunt_path(rendered_step, _step_env):
    return rendered_step
