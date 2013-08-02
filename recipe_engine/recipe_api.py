# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import imp
import inspect
import os
import sys
import tempfile


class Placeholder(object):
  """Base class for json placeholders. Do not use directly."""
  def render(self, test_data):  # pragma: no cover
    """Return [cmd items]*"""
    raise NotImplementedError

  def step_finished(self, presentation, step_result, test_data):
    """Called after step completion. Intended to modify step_result."""
    pass


class InputDataPlaceholder(Placeholder):
  def __init__(self, data, suffix):
    assert isinstance(data, basestring)
    self.data = data
    self.suffix = suffix
    self.input_file = None
    super(InputDataPlaceholder, self).__init__()

  def render(self, test_data):
    if test_data is not None:
      # cheat and pretend like we're going to pass the data on the
      # cmdline for test expectation purposes.
      return [self.data]
    else:  # pragma: no cover
      input_fd, self.input_file = tempfile.mkstemp(suffix=self.suffix)
      os.write(input_fd, self.data)
      os.close(input_fd)
      return [self.input_file]

  def step_finished(self, presentation, step_result, test_data):
    if test_data is None:  # pragma: no cover
      os.unlink(self.input_file)


class ModuleInjectionSite(object):
  pass


class RecipeApi(object):
  """
  Framework class for handling recipe_modules.

  Inherit from this in your recipe_modules/<name>/api.py . This class provides
  wiring for your config context (in self.c and methods, and for dependency
  injection (in self.m).

  Dependency injection takes place in load_recipe_modules() below.
  """
  def __init__(self, module=None, mock=None, **_kwargs):
    """Note: Injected dependencies are NOT available in __init__()."""
    self.c = None
    self._module = module
    self._mock = mock

    # If we're the 'root' api, inject directly into 'self'.
    # Otherwise inject into 'self.m'
    self.m = self if module is None else ModuleInjectionSite()

  def get_config_defaults(self, _config_name):  # pylint: disable=R0201
    """
    Allows your api to dynamically determine static default values for configs.
    """
    return {}

  def make_config(self, config_name=None, optional=False, **CONFIG_VARS):
    """Returns a 'config blob' for the current API."""
    ctx = self._module.CONFIG_CTX
    if optional and not ctx:
      return

    assert ctx, '%s has no config context' % self
    params = self.get_config_defaults(config_name)
    params.update(CONFIG_VARS)
    try:
      base = ctx.CONFIG_SCHEMA(**params)
      if config_name is None:
        return base
      else:
        return ctx.CONFIG_ITEMS[config_name](base)
    except KeyError:
      if optional:
        return
      else:
        raise  # TODO(iannucci): raise a better exception.

  def set_config(self, config_name, optional=False, **CONFIG_VARS):
    """Sets the modules and its dependencies to the named configuration."""
    assert self._module
    config = self.make_config(config_name, optional, **CONFIG_VARS)
    if config:
      self.c = config
    # TODO(iannucci): This is 'inefficient', since if a dep comes up multiple
    # times in this recursion, it will get set_config()'d multiple times
    for dep in self._module.DEPS:
      getattr(self.m, dep).set_config(config_name, optional=True, **CONFIG_VARS)

  def apply_config(self, config_name, config_object=None):
    """Apply a named configuration to the provided config object or self."""
    self._module.CONFIG_CTX.CONFIG_ITEMS[config_name](config_object or self.c)


def load_recipe_modules(mod_dirs):
  def patchup_module(submod):
    submod.CONFIG_CTX = getattr(submod, 'CONFIG_CTX', None)
    submod.API = getattr(submod, 'API', None)
    submod.DEPS = frozenset(getattr(submod, 'DEPS', ()))

    if hasattr(submod, 'config'):
      for v in submod.config.__dict__.itervalues():
        if hasattr(v, 'I_AM_A_CONFIG_CTX'):
          assert not submod.CONFIG_CTX, (
            'More than one configuration context: %s' % (submod.config))
          submod.CONFIG_CTX = v
      assert submod.CONFIG_CTX, 'Config file, but no config context?'

    for v in submod.api.__dict__.itervalues():
      if inspect.isclass(v) and issubclass(v, RecipeApi):
        assert not submod.API, (
          'More than one Api subclass: %s' % submod.api)
        submod.API = v

    assert submod.API, 'Submodule has no api? %s' % (submod)

  RM = 'RECIPE_MODULES'
  def find_and_load(fullname, modname, path):
    if fullname not in sys.modules or fullname == RM:
      try:
        fil, pathname, descr = imp.find_module(modname,
                                               [os.path.dirname(path)])
        imp.load_module(fullname, fil, pathname, descr)
      finally:
        if fil:
          fil.close()
    return sys.modules[fullname]

  def recursive_import(path, prefix=None, skip_fn=lambda name: False):
    modname = os.path.splitext(os.path.basename(path))[0]
    if prefix:
      fullname = '%s.%s' % (prefix, modname)
    else:
      fullname = RM
    m = find_and_load(fullname, modname, path)
    if not os.path.isdir(path):
      return m

    for subitem in os.listdir(path):
      subpath = os.path.join(path, subitem)
      subname = os.path.splitext(subitem)[0]
      if skip_fn(subname):
        continue
      if os.path.isdir(subpath):
        if not os.path.exists(os.path.join(subpath, '__init__.py')):
          continue
      elif not subpath.endswith('.py') or subitem.startswith('__init__.py'):
        continue

      submod = recursive_import(subpath, fullname, skip_fn=skip_fn)

      if not hasattr(m, subname):
        setattr(m, subname, submod)
      else:
        prev = getattr(m, subname)
        assert submod is prev, (
          'Conflicting modules: %s and %s' % (prev, m))

    return m

  imp.acquire_lock()
  try:
    if RM not in sys.modules:
      sys.modules[RM] = imp.new_module(RM)
      # First import all the APIs and configs
      for root in mod_dirs:
        if os.path.isdir(root):
          recursive_import(root, skip_fn=lambda name: name.endswith('_config'))

      # Then fixup all the modules
      for name, submod in sys.modules[RM].__dict__.iteritems():
        if name[0] == '_':
          continue
        patchup_module(submod)

      # Then import all the config extenders.
      for root in mod_dirs:
        if os.path.isdir(root):
          recursive_import(root)
    return sys.modules[RM]
  finally:
    imp.release_lock()


def CreateRecipeApi(names, mod_dirs, mocks=None, **kwargs):
  """
  Given a list of module names, return an instance of RecipeApi which contains
  those modules as direct members.

  So, if you pass ['foobar'], you'll get an instance back which contains a
  'foobar' attribute which itself is a RecipeApi instance from the 'foobar'
  module.

  Args:
    names (list): A list of module names to include in the returned RecipeApi.
    mod_dirs (list): A list of paths to directories which contain modules.
    mocks (dict): An optional dict of {<modname>: <mock data>}. Each module
        expects its own mock data.
    **kwargs: Data passed to each module api. Usually this will contain:
        properties (dict): the properties dictionary (used by the properties
            module)
        step_history (OrderedDict): the step history object (used by the
            step_history module!)
  """

  recipe_modules = load_recipe_modules(mod_dirs)

  inst_map = {None: RecipeApi()}
  dep_map = {None: set(names)}
  def create_maps(name):
    if name not in dep_map:
      module = getattr(recipe_modules, name)

      dep_map[name] = set(module.DEPS)
      map(create_maps, dep_map[name])

      mock = None if mocks is None else mocks.get(name, {})
      inst_map[name] = module.API(module=module, mock=mock, **kwargs)
  map(create_maps, names)

  # NOTE: this is 'inefficient', but correct and compact.
  did_something = True
  while dep_map:
    did_something = False
    to_pop = []
    for api_name, deps in dep_map.iteritems():
      to_remove = []
      for dep in [d for d in deps if d not in dep_map]:
        # Grab the injection site
        obj = inst_map[api_name].m
        assert not hasattr(obj, dep)
        setattr(obj, dep, inst_map[dep])
        to_remove.append(dep)
        did_something = True
      map(deps.remove, to_remove)
      if not deps:
        to_pop.append(api_name)
        did_something = True
    map(dep_map.pop, to_pop)
    assert did_something, 'Did nothing on this loop. %s' % dep_map

  return inst_map[None]
