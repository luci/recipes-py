# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from .recipe_test_api import DisabledTestData, ModuleTestData

from .recipe_util import ModuleInjectionSite


class RecipeApi(ModuleInjectionSite):
  """
  Framework class for handling recipe_modules.

  Inherit from this in your recipe_modules/<name>/api.py . This class provides
  wiring for your config context (in self.c and methods, and for dependency
  injection (in self.m).

  Dependency injection takes place in load_recipe_modules() below.
  """
  def __init__(self, module=None, test_data=DisabledTestData(), **_kwargs):
    """Note: Injected dependencies are NOT available in __init__()."""
    super(RecipeApi, self).__init__()

    self.c = None
    self._module = module

    assert isinstance(test_data, (ModuleTestData, DisabledTestData))
    self._test_data = test_data

    # If we're the 'root' api, inject directly into 'self'.
    # Otherwise inject into 'self.m'
    self.m = self if module is None else ModuleInjectionSite(self)

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

  @property
  def name(self):
    return self._module.NAME
