# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import types

from functools import wraps

from .recipe_test_api import DisabledTestData, ModuleTestData

from .recipe_util import ModuleInjectionSite

class StepFailure(Exception):
  """
  This is the base class for all step failures.
  """
  def __init__(self, name_or_reason, result=None):
    if result:
      self.name = name_or_reason
      self.result = result
      self.reason = self.reason_message()
    else:
      self.name = None
      self.result = None
      self.reason = name_or_reason

    super(StepFailure, self).__init__(self.reason)

  def reason_message(self):
    return "Step({!r}) failed with return_code {}".format(
        self.name, self.result.retcode)

  def __str__(self):
    return "Step Failure in %s" % self.name

  @property
  def retcode(self):
    """
    Returns the retcode of the step which failed. If this was a manual
    failure, returns None
    """
    if not self.result:
      return None
    return self.result.retcode

class StepWarning(StepFailure):
  """
  A subclass of StepFailure, which still fails the build, but which is
  a warning. Need to figure out how exactly this will be useful.
  """
  def reason_message(self):
    return "Warning: Step({!r}) returned {}".format(
          self.name, self.result.retcode)

  def __str__(self):
    return "Step Warning in %s" % self.name

class InfraFailure(StepFailure):
  """
  A subclass of StepFailure, which fails the build due to problems with the
  infrastructure.
  """
  def reason_message(self):
    return "Infra Failure: Step({!r}) returned {}".format(
          self.name, self.result.retcode)

  def __str__(self):
    return "Infra Failure in %s" % self.name


class AggregatedStepFailure(StepFailure):
  def __init__(self, result):
    super(AggregatedStepFailure, self).__init__(
            "Aggregate step failure.", result=result)

  def reason_message(self):
    msg = "{!r} out of {!r} aggregated steps failed. Failures: ".format(
        len(self.result.failures), len(self.result.all_results))
    msg += ', '.join((f.reason or f.name) for f in self.result.failures)
    return msg

  def __str__(self):
    return "Aggregate Step Failure"


class AggregatedResult(object):
  """Holds the result of an aggregated run of steps.

  Currently this is only used internally by defer_results, but it may be exposed
  to the consumer of defer_results at some point in the future. For now it's
  expected to be easier for defer_results consumers to do their own result
  aggregation, as they may need to pick and chose (or label) which results they
  really care about.
  """
  def __init__(self):
    self.successes = []
    self.failures = []

    # Needs to be here to be able to treat this as a step result
    self.retcode = None

  @property
  def all_results(self):
    """
    Return a list of two item tuples (x, y), where
      x is whether or not the step succeeded, and
      y is the result of the run
    """
    res = [(True, result) for result in self.successes]
    res.extend([(False, result) for result in self.failures])
    return res

  def add_success(self, result):
    self.successes.append(result)

  def add_failure(self, exception):
    self.failures.append(exception)

  def get_result(self, should_raise=True):
    if self.failures and should_raise:
      raise AggregatedStepFailure(self)
    return self.all_results


class DeferredResult(object):
  def __init__(self, result, failure):
    self._result = result
    self._failure = failure

  @property
  def is_ok(self):
    return self._failure is None

  def get_result(self):
    if not self.is_ok:
      raise self.get_error()
    return self._result

  def get_error(self):
    assert self._failure, "WHAT IS IT ARE YOU DOING???!?!?!? SHTAP NAO"
    return self._failure


_AGGREGATOR = None


def non_step(func):
  """A decorator which prevents a method from automatically being wrapped as
  a composite_step by RecipeApiMeta.

  This is needed for utility methods which don't run any steps, but which are
  invoked within the context of a defer_results().

  @see composite_step, defer_results, RecipeApiMeta
  """
  func._non_step = True
  return func


def composite_step(func):
  """A decorator which makes this step act as a single step, for the purposes of
  the defer_results function.

  This means that this function will not quit during the middle of its execution
  because of a StepFailure, if there is an aggregator active.

  There is NO penalty to adding this decorator to a function. Please do it.

  RecipeApiMeta (the metaclass for RecipeApi) automatically applies this
  decorator to all methods of the Api (unless func was already wrapped with
  non_step).
  """
  if getattr(func, "_non_step", False):
    return func
  @wraps(func)
  def _inner(*a, **kw):
    global _AGGREGATOR
    if _AGGREGATOR is None:
      return func(*a, **kw)

    # We pull the current aggregator off here and restore it in the finally
    # block at the end.  This allows us to use the call stack to maintain the
    # state of the global _AGGREGATOR without a separate global stack.
    agg = _AGGREGATOR

    # Setting the _AGGREGATOR to None allows the contents of func to be
    # written in the same style (e.g. with exceptions) no matter how func is
    # being called.
    _AGGREGATOR = None
    try:
      ret = func(*a, **kw)
      agg.add_success(ret)
      return DeferredResult(ret, None)
    except StepFailure as ex:
      agg.add_failure(ex)
      return DeferredResult(None, ex)
    finally:
      _AGGREGATOR = agg
  return _inner

@contextlib.contextmanager
def defer_results():
  """
  Use this to defer step results in your code. All steps which would previously
    return a result or throw an exception will instead return a DeferredResult.

  Any exceptions which were thrown during execution will be thrown when either:
    a. You call get_result() on the step's result.
    b. You exit the suite inside of the with statement

  Example:
    with defer_results():
      api.step('a', ..)
      api.step('b', ..)
      result = api.m.module.im_a_composite_step(...)
      api.m.echo('the data is', result.get_result())

  If 'a' fails, 'b' and 'im a composite step'  will still run.
  If 'im a composite step' fails, then the get_result() call will raise
    an exception.
  If you don't try to use the result (don't call get_result()), an aggregate
    failure will still be raised once you exit the suite inside
    the with statement.
  """
  global _AGGREGATOR

  # It doesn't make sense to nest defer_results context without traversing
  # a composite_step function first. If you really need this, then you could
  # also create an intermediate composite_step to contain the second
  # defer_results clause
  assert _AGGREGATOR is None, (
    "may not call defer_results while in an active defer_results context"
  )

  try:
    _AGGREGATOR = AggregatedResult()
    yield
    if _AGGREGATOR.failures:
      raise AggregatedStepFailure(_AGGREGATOR)
  finally:
    # Since we assert that _AGGREGATOR is None, we're assigning it back to
    # None here, thus completing the loop. If we ever remove the assert above,
    # we'll need to change this as well.
    _AGGREGATOR = None


class RecipeApiMeta(type):
  def __new__(mcs, name, bases, attrs):
    """Automatically wraps all methods of subclasses of RecipeApi with
    @composite_step. This allows defer_results to work as intended at all
    times.
    """
    wrap = lambda f: composite_step(f) if f else f
    for attr in attrs:
      val = attrs[attr]
      if isinstance(val, types.FunctionType):
        attrs[attr] = wrap(val)
      elif isinstance(val, property):
        attrs[attr] = property(
          wrap(val.fget),
          wrap(val.fset),
          wrap(val.fdel),
          val.__doc__)
    return super(RecipeApiMeta, mcs).__new__(mcs, name, bases, attrs)


class RecipeApiPlain(ModuleInjectionSite):
  """
  Framework class for handling recipe_modules.

  Inherit from this in your recipe_modules/<name>/api.py . This class provides
  wiring for your config context (in self.c and methods, and for dependency
  injection (in self.m).

  Dependency injection takes place in load_recipe_modules() in recipe_loader.py.

  USE RecipeApi INSTEAD, UNLESS your RecipeApi subclass derives from something
  which defines its own __metaclass__. Deriving from RecipeApi instead of
  RecipeApiPlain allows your RecipeApi subclass to automatically work with
  defer_results without needing to decorate your methods with @composite_step.
  """

  def __init__(self, module=None, engine=None,
               test_data=DisabledTestData(), **_kwargs):
    """Note: Injected dependencies are NOT available in __init__()."""
    super(RecipeApiPlain, self).__init__()

    # |engine| is an instance of annotated_run.RecipeEngine. Modules should not
    # generally use it unless they're low-level framework level modules.
    self._engine = engine
    self._module = module

    assert isinstance(test_data, (ModuleTestData, DisabledTestData))
    self._test_data = test_data

    # If we're the 'root' api, inject directly into 'self'.
    # Otherwise inject into 'self.m'
    self.m = self if module is None else ModuleInjectionSite(self)

    # If our module has a test api, it gets injected here.
    self.test_api = None

    # Config goes here.
    self.c = None

  def get_config_defaults(self):  # pylint: disable=R0201
    """
    Allows your api to dynamically determine static default values for configs.
    """
    return {}

  def make_config(self, config_name=None, optional=False, **CONFIG_VARS):
    """Returns a 'config blob' for the current API."""
    return self.make_config_params(config_name, optional, **CONFIG_VARS)[0]

  def make_config_params(self, config_name, optional=False, **CONFIG_VARS):
    """Returns a 'config blob' for the current API, and the computed params
    for all dependent configurations.

    The params have the following order of precendence. Each subsequent param
    is dict.update'd into the final parameters, so the order is from lowest to
    higest precedence on a per-key basis:
      * if config_name in CONFIG_CTX
        * get_config_defaults()
        * CONFIG_CTX[config_name].DEFAULT_CONFIG_VARS()
        * CONFIG_VARS
      * else
        * get_config_defaults()
        * CONFIG_VARS
    """
    generic_params = self.get_config_defaults()  # generic defaults
    generic_params.update(CONFIG_VARS)           # per-invocation values

    ctx = self._module.CONFIG_CTX
    if optional and not ctx:
      return None, generic_params

    assert ctx, '%s has no config context' % self
    try:
      params = self.get_config_defaults()         # generic defaults
      itm = ctx.CONFIG_ITEMS[config_name] if config_name else None
      if itm:
        params.update(itm.DEFAULT_CONFIG_VARS())  # per-item defaults
      params.update(CONFIG_VARS)                  # per-invocation values

      base = ctx.CONFIG_SCHEMA(**params)
      if config_name is None:
        return base, params
      else:
        return itm(base), params
    except KeyError:
      if optional:
        return None, generic_params
      else:
        raise  # TODO(iannucci): raise a better exception.

  def set_config(self, config_name=None, optional=False, include_deps=True,
                 **CONFIG_VARS):
    """Sets the modules and its dependencies to the named configuration."""
    assert self._module
    config, params = self.make_config_params(config_name, optional,
                                             **CONFIG_VARS)
    if config:
      self.c = config

    if include_deps:
      # TODO(iannucci): This is 'inefficient', since if a dep comes up multiple
      # times in this recursion, it will get set_config()'d multiple times
      for dep in self._module.DEPS:
        getattr(self.m, dep).set_config(config_name, optional=True, **params)

  def apply_config(self, config_name, config_object=None):
    """Apply a named configuration to the provided config object or self."""
    self._module.CONFIG_CTX.CONFIG_ITEMS[config_name](config_object or self.c)

  def resource(self, *path):
    """Returns path to a file under <recipe module>/resources/ directory.

    Args:
      path: path relative to module's resources/ directory.
    """
    # TODO(vadimsh): Verify that file exists. Including a case like:
    #  module.resource('dir').join('subdir', 'file.py')
    return self._module.MODULE_DIRECTORY.join('resources', *path)

  @property
  def name(self):
    return self._module.NAME


class RecipeApi(RecipeApiPlain):
  __metaclass__ = RecipeApiMeta
