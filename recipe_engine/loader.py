# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy
import imp
import inspect
import os
import sys

from .recipe_util import RECIPE_DIRS, MODULE_DIRS, cached_unary, scan_directory
from .recipe_api import RecipeApi
from .recipe_config import ConfigContext
from .recipe_test_api import RecipeTestApi, DisabledTestData


class NoSuchRecipe(Exception):
  """Raised by load_recipe is recipe is not found."""


class RecipeScript(object):
  """Holds dict of an evaluated recipe script."""

  def __init__(self, recipe_dict):
    for k, v in recipe_dict.iteritems():
      setattr(self, k, v)

  @classmethod
  def from_script_path(cls, script_path):
    """Evaluates a script and returns RecipeScript instance."""
    script_vars = {}
    execfile(script_path, script_vars)
    return cls(script_vars)

  @classmethod
  def from_module_object(cls, module_obj):
    """Converts python module object into RecipeScript instance."""
    return cls(module_obj.__dict__)


def load_recipe_modules(mod_dirs):
  """Makes a python module object that have all recipe modules in its dict.

  Args:
    mod_dirs (list of str): list of module search paths.
  """
  def patchup_module(name, submod):
    """Finds framework related classes and functions in a |submod| and adds
    them to |submod| as top level constants with well known names such as
    API, CONFIG_CTX and TEST_API.

    |submod| is a recipe module (akin to python package) with submodules such as
    'api', 'config', 'test_api'. This function scans through dicts of that
    submodules to find subclasses of RecipeApi, RecipeTestApi, etc.
    """
    submod.NAME = name
    submod.CONFIG_CTX = getattr(submod, 'CONFIG_CTX', None)
    submod.DEPS = frozenset(getattr(submod, 'DEPS', ()))

    if hasattr(submod, 'config'):
      for v in submod.config.__dict__.itervalues():
        if isinstance(v, ConfigContext):
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


def create_apis(mod_dirs, names, only_test_api, engine, test_data):
  """Given a list of module names, return linked instances of RecipeApi
  and RecipeTestApi (in a pair) which contains those modules as direct members.

  So, if you pass ['foobar'], you'll get an instance back which contains a
  'foobar' attribute which itself is a RecipeApi instance from the 'foobar'
  module.

  Args:
    mod_dirs (list): A list of paths to directories which contain modules.
    names (list): A list of module names to include in the returned RecipeApi.
    only_test_api (bool): If True, do not create RecipeApi, only RecipeTestApi.
    engine (object): A recipe engine instance that gets passed to each API.
      Among other things it provides:
        properties (dict): the properties dictionary (used by the properties
            module)
        step_history (OrderedDict): the step history object (used by the
            step_history module!)
      See annotated_run.py for definition.
    test_data (TestData): ...

  Returns:
    Pair (RecipeApi instance or None, RecipeTestApi instance).
  """
  recipe_modules = load_recipe_modules(mod_dirs)

  # Recipe module name (or None for top level API) -> RecipeTestApi instance.
  test_apis = {}
  # Recipe module name (or None for top level API) -> RecipeApi instance.
  apis = {}

  # 'None' keys represent top level API objects returned by this function.
  test_apis[None] = RecipeTestApi(module=None)
  if not only_test_api:
    apis[None] = RecipeApi(module=None,
                           engine=engine,
                           test_data=test_data.get_module_test_data(None))

  dep_map = {None: set(names)}
  def create_maps(name):
    if name not in dep_map:
      module = getattr(recipe_modules, name)

      dep_map[name] = set(module.DEPS)
      map(create_maps, dep_map[name])

      test_api_cls = getattr(module, 'TEST_API', None) or RecipeTestApi
      test_apis[name] = test_api_cls(module=module)

      if not only_test_api:
        api_cls = getattr(module, 'API')
        apis[name] = api_cls(module=module,
                             engine=engine,
                             test_data=test_data.get_module_test_data(name))

  map(create_maps, names)

  map_dependencies(dep_map, test_apis)
  if not only_test_api:
    map_dependencies(dep_map, apis)
    for name, module in apis.iteritems():
      module.test_api = test_apis[name]

  return apis.get(None), test_apis.get(None)


def map_dependencies(dep_map, inst_map):
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


def create_recipe_api(names, engine, test_data=DisabledTestData()):
  return create_apis(MODULE_DIRS(), names, False, engine, test_data)[0]


def create_test_api(names):
  # Test API should not use runtime engine or test_data, do not pass it.
  return create_apis(MODULE_DIRS(), names, True, None, DisabledTestData())[1]


@cached_unary
def load_recipe(recipe):
  """Given name of a recipe, loads and returns it as RecipeScript instance.

  Args:
    recipe (str): name of a recipe, can be in form '<module>:<recipe>'.

  Returns:
    RecipeScript instance.

  Raises:
    NoSuchRecipe: recipe is not found.
  """
  # If the recipe is specified as "module:recipe", then it is an recipe
  # contained in a recipe_module as an example. Look for it in the modules
  # imported by load_recipe_modules instead of the normal search paths.
  if ':' in recipe:
    module_name, example = recipe.split(':')
    assert example.endswith('example')
    RECIPE_MODULES = load_recipe_modules(MODULE_DIRS())
    try:
      script_module = getattr(getattr(RECIPE_MODULES, module_name), example)
      return RecipeScript.from_module_object(script_module)
    except AttributeError:
      raise NoSuchRecipe(recipe,
                         'Recipe module %s does not have example %s defined' %
                         (module_name, example))
  else:
    for recipe_path in (os.path.join(p, recipe) for p in RECIPE_DIRS()):
      if os.path.exists(recipe_path + '.py'):
        return RecipeScript.from_script_path(recipe_path + '.py')
    raise NoSuchRecipe(recipe)


def loop_over_recipes():
  """Yields pairs (path to recipe, recipe name).

  Enumerates real recipes in recipes/* as well as examples in recipe_modules/*.
  """
  for path in RECIPE_DIRS():
    for recipe in scan_directory(
        path, lambda f: f.endswith('.py') and f[0] != '_'):
      yield recipe, recipe[len(path)+1:-len('.py')]
  for path in MODULE_DIRS():
    for recipe in scan_directory(
        path, lambda f: f.endswith('example.py')):
      module_name = os.path.dirname(recipe)[len(path)+1:]
      yield recipe, '%s:example' % module_name
