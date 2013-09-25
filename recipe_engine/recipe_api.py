# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools

from .recipe_test_api import DisabledTestData, ModuleTestData, StepTestData

from .recipe_util import ModuleInjectionSite


class RecipeApi(object):
  """
  Framework class for handling recipe_modules.

  Inherit from this in your recipe_modules/<name>/api.py . This class provides
  wiring for your config context (in self.c and methods, and for dependency
  injection (in self.m).

  Dependency injection takes place in load_recipe_modules() below.
  """
  def __init__(self, module=None, test_data=DisabledTestData(), **_kwargs):
    """Note: Injected dependencies are NOT available in __init__()."""
    self.c = None
    self._module = module

    assert isinstance(test_data, (ModuleTestData, DisabledTestData))
    self._test_data = test_data

    # If we're the 'root' api, inject directly into 'self'.
    # Otherwise inject into 'self.m'
    self.m = self if module is None else ModuleInjectionSite()

    # If our module has a test api, it gets injected here.
    self.test_api = None

  def get_config_defaults(self):  # pylint: disable=R0201
    """
    Allows your api to dynamically determine static default values for configs.
    """
    return {}

  def make_config(self, config_name=None, optional=False, **CONFIG_VARS):
    """Returns a 'config blob' for the current API."""
    return self.make_config_params(config_name, optional, **CONFIG_VARS)[0]

  def make_config_params(self, config_name=None, optional=False, **CONFIG_VARS):
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

  def set_config(self, config_name, optional=False, **CONFIG_VARS):
    """Sets the modules and its dependencies to the named configuration."""
    assert self._module
    config, params = self.make_config_params(config_name, optional,
                                             **CONFIG_VARS)
    if config:
      self.c = config
    # TODO(iannucci): This is 'inefficient', since if a dep comes up multiple
    # times in this recursion, it will get set_config()'d multiple times
    for dep in self._module.DEPS:
      getattr(self.m, dep).set_config(config_name, optional=True, **params)

  def apply_config(self, config_name, config_object=None):
    """Apply a named configuration to the provided config object or self."""
    self._module.CONFIG_CTX.CONFIG_ITEMS[config_name](config_object or self.c)

  @property
  def name(self):
    return self._module.NAME


def inject_test_data(func):
  """
  Decorator which injects mock data from this module's test_api method into
  the return value of the decorated function.

  The return value of func MUST be a single step dictionary (specifically,
  |func| must not be a generator, nor must it return a list of steps, etc.)

  When the decorated function is called, |func| is called normally. If we are
  in test mode, we will then also call self.test_api.<func.__name__>, whose
  return value will be assigned into the step dictionary retuned by |func|.

  It is an error for the function to not exist in the test_api.
  It is an error for the return value of |func| to already contain test data.
  """
  @functools.wraps(func)
  def inner(self, *args, **kwargs):
    assert isinstance(self, RecipeApi)
    ret = func(self, *args, **kwargs)
    if self._test_data.enabled:  # pylint: disable=W0212
      test_fn = getattr(self.test_api, func.__name__, None)
      assert test_fn, (
        "Method %(meth)s in module %(mod)s is @inject_test_data, but test_api"
        " does not contain %(meth)s."
        % {
          'meth': func.__name__,
          'mod': self._module,  # pylint: disable=W0212
        })
      assert 'default_step_data' not in ret
      data = test_fn(*args, **kwargs)
      assert isinstance(data, StepTestData)
      ret['default_step_data'] = data
    return ret
  return inner
