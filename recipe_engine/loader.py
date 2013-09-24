# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import copy
import imp
import inspect
import os
import sys

from common import chromium_utils

from .recipe_util import RECIPE_DIRS, MODULE_DIRS
from .recipe_api import RecipeApi
from .recipe_test_api import RecipeTestApi, DisabledTestData, ModuleTestData


def load_recipe_modules(mod_dirs):
  def patchup_module(name, submod):
    submod.NAME = name
    submod.CONFIG_CTX = getattr(submod, 'CONFIG_CTX', None)
    submod.DEPS = frozenset(getattr(submod, 'DEPS', ()))

    if hasattr(submod, 'config'):
      for v in submod.config.__dict__.itervalues():
        if hasattr(v, 'I_AM_A_CONFIG_CTX'):
          assert not submod.CONFIG_CTX, (
            'More than one configuration context: %s' % (submod.config))
          submod.CONFIG_CTX = v
      assert submod.CONFIG_CTX, 'Config file, but no config context?'

    submod.API = getattr(submod, 'API', None)
    for v in submod.api.__dict__.itervalues():
      if inspect.isclass(v) and issubclass(v, RecipeApi):
        assert not submod.API, (
          'More than one Api subclass: %s' % submod.api)
        submod.API = v
    assert submod.API, 'Submodule has no api? %s' % (submod)

    submod.TEST_API = getattr(submod, 'TEST_API', None)
    if hasattr(submod, 'test_api'):
      for v in submod.test_api.__dict__.itervalues():
        if inspect.isclass(v) and issubclass(v, RecipeTestApi):
          assert not submod.TEST_API, (
            'More than one TestApi subclass: %s' % submod.api)
          submod.TEST_API = v
      assert submod.API, (
        'Submodule has test_api.py but no TestApi subclass? %s'
        % (submod)
      )

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
        patchup_module(name, submod)

      # Then import all the config extenders.
      for root in mod_dirs:
        if os.path.isdir(root):
          recursive_import(root)
    return sys.modules[RM]
  finally:
    imp.release_lock()


def CreateApi(mod_dirs, names, test_data=DisabledTestData(), required=None,
              optional=None, kwargs=None):
  """
  Given a list of module names, return an instance of RecipeApi which contains
  those modules as direct members.

  So, if you pass ['foobar'], you'll get an instance back which contains a
  'foobar' attribute which itself is a RecipeApi instance from the 'foobar'
  module.

  Args:
    names (list): A list of module names to include in the returned RecipeApi.
    mod_dirs (list): A list of paths to directories which contain modules.
    test_data (TestData): ...
    kwargs: Data passed to each module api. Usually this will contain:
        properties (dict): the properties dictionary (used by the properties
            module)
        step_history (OrderedDict): the step history object (used by the
            step_history module!)
  """
  kwargs = kwargs or {}
  recipe_modules = load_recipe_modules(mod_dirs)

  inst_maps = {}
  if required:
    inst_maps[required[0]] = { None: required[1]() }
  if optional:
    inst_maps[optional[0]] = { None: optional[1]() }

  dep_map = {None: set(names)}
  def create_maps(name):
    if name not in dep_map:
      module = getattr(recipe_modules, name)

      dep_map[name] = set(module.DEPS)
      map(create_maps, dep_map[name])

      mod_test = DisabledTestData()
      if test_data.enabled:
        mod_test = test_data.mod_data.get(name, ModuleTestData())

      if required:
        api = getattr(module, required[0])
        inst_maps[required[0]][name] = api(module=module,
                                           test_data=mod_test, **kwargs)
      if optional:
        api = getattr(module, optional[0], None) or optional[1]
        inst_maps[optional[0]][name] = api(module=module,
                                           test_data=mod_test)

  map(create_maps, names)

  if required:
    MapDependencies(dep_map, inst_maps[required[0]])
  if optional:
    MapDependencies(dep_map, inst_maps[optional[0]])
    if required:
      for name, module in inst_maps[required[0]].iteritems():
        module.test_api = inst_maps[optional[0]][name]

  return inst_maps[(required or optional)[0]][None]


def MapDependencies(dep_map, inst_map):
  # NOTE: this is 'inefficient', but correct and compact.
  dep_map = copy.deepcopy(dep_map)
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


def CreateTestApi(names):
  return CreateApi(MODULE_DIRS(), names, optional=('TEST_API', RecipeTestApi))


def CreateRecipeApi(names, test_data=DisabledTestData(), **kwargs):
  return CreateApi(MODULE_DIRS(), names, test_data=test_data, kwargs=kwargs,
                   required=('API', RecipeApi),
                   optional=('TEST_API', RecipeTestApi))


class NoSuchRecipe(Exception):
  pass


def LoadRecipe(recipe):
  # If the recipe is specified as "module:recipe", then it is an recipe
  # contained in a recipe_module as an example. Look for it in the modules
  # imported by load_recipe_modules instead of the normal search paths.
  if ':' in recipe:
    module_name, example = recipe.split(':')
    assert example.endswith('example')
    RECIPE_MODULES = load_recipe_modules(MODULE_DIRS())
    try:
      return getattr(getattr(RECIPE_MODULES, module_name), example)
    except AttributeError:
      pass
  else:
    for recipe_path in (os.path.join(p, recipe) for p in RECIPE_DIRS()):
      recipe_module = chromium_utils.IsolatedImportFromPath(recipe_path)
      if recipe_module:
        return recipe_module
  raise NoSuchRecipe(recipe)


def find_recipes(path, predicate):
  for root, _dirs, files in os.walk(path):
    for recipe in (f for f in files if predicate(f)):
      recipe_path = os.path.join(root, recipe)
      yield recipe_path


def loop_over_recipes():
  for path in RECIPE_DIRS():
    for recipe in find_recipes(
        path, lambda f: f.endswith('.py') and f[0] != '_'):
      yield recipe, recipe[len(path)+1:-len('.py')]
  for path in MODULE_DIRS():
    for recipe in find_recipes(
        path, lambda f: f.endswith('example.py')):
      module_name = os.path.dirname(recipe)[len(path)+1:]
      yield recipe, '%s:example' % module_name
