# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import collections
import contextlib
import imp
import inspect
import os
import sys

from . import env

from .config import ConfigContext, ConfigGroupSchema
from .config_types import Path, ModuleBasePath, PackageRepoBasePath
from .config_types import RECIPE_MODULE_PREFIX
from .recipe_api import RecipeApi, RecipeApiPlain, RecipeScriptApi
from .recipe_api import Property, BoundProperty
from .recipe_api import UndefinedPropertyException, PROPERTY_SENTINEL
from .recipe_test_api import RecipeTestApi, DisabledTestData
from .util import scan_directory


class LoaderError(Exception):
  """Raised when something goes wrong loading recipes or modules."""


class NoSuchRecipe(LoaderError):
  """Raised by load_recipe is recipe is not found."""
  def __init__(self, recipe):
    super(NoSuchRecipe, self).__init__('No such recipe: %s' % recipe)


class RecipeScript(object):
  """Holds dict of an evaluated recipe script."""

  def __init__(self, recipe_globals, name):
    self.name = name
    self._recipe_globals = recipe_globals

    self.run_steps, self.gen_tests = [
        recipe_globals.get(k) for k in ('RunSteps', 'GenTests')]

    # Let each property object know about the property name.
    recipe_globals['PROPERTIES'] = {
        name: value.bind(name, BoundProperty.RECIPE_PROPERTY, name)
        for name, value in recipe_globals.get('PROPERTIES', {}).items()}

    return_schema = recipe_globals.get('RETURN_SCHEMA')
    if return_schema and not isinstance(return_schema, ConfigGroupSchema):
      raise ValueError('Invalid RETURN_SCHEMA; must be an instance of '
                       'ConfigGroupSchema')

  @property
  def globals(self):
    return self._recipe_globals

  @property
  def PROPERTIES(self):
    return self._recipe_globals['PROPERTIES']

  @property
  def LOADED_DEPS(self):
    return self._recipe_globals['LOADED_DEPS']

  @property
  def RETURN_SCHEMA(self):
    return self._recipe_globals.get('RETURN_SCHEMA')

  def run(self, api, properties):
    """
    Run this recipe, with the given api and property arguments.
    Check the return value, if we have a RETURN_SCHEMA.
    """
    recipe_result = invoke_with_properties(
      self.run_steps, properties, self.PROPERTIES, api=api)

    if self.RETURN_SCHEMA:
      if not recipe_result:
        raise ValueError("Recipe %s did not return a value." % self.name)
      return recipe_result.as_jsonish(True)
    else:
      return None

  @classmethod
  def from_script_path(cls, script_path, universe_view):
    """Evaluates a script and returns RecipeScript instance."""

    recipe_globals = {}
    recipe_globals['__file__'] = script_path

    with env.temp_sys_path():
      execfile(script_path, recipe_globals)

    recipe_globals['LOADED_DEPS'] = universe_view.deps_from_spec(
        recipe_globals.get('DEPS', []))

    # 'a/b/c/my_name.py' -> my_name
    name = os.path.basename(script_path).split('.')[0]
    return cls(recipe_globals, name)


class RecipeUniverse(object):
  def __init__(self, package_deps, config_file):
    self._loaded = {}
    self._package_deps = package_deps
    self._config_file = config_file

  @property
  def module_dirs(self):
    for package in self._package_deps.packages:
      for module_dir in package.module_dirs:
        yield module_dir

  @property
  def recipe_dirs(self):
    for package in self._package_deps.packages:
      for recipe_dir in package.recipe_dirs:
        yield recipe_dir

  @property
  def config_file(self):
    return self._config_file

  @property
  def packages(self):
    return list(self._package_deps.packages)

  @property
  def package_deps(self):
    return self._package_deps

  def load(self, package, name):
    """Load a recipe module, identified by a name inside of a package"""
    key = (package.name, name)
    if key in self._loaded:
      mod = self._loaded[key]
      assert mod is not None, (
          'Cyclic dependency when trying to load %r' % name)
      return mod
    else:
      self._loaded[key] = None

      path = package.module_path(name)

      assert os.path.isabs(path), (
          'Path dependencies must be absolute, but %r is not' % path)

      try:
        mod = _load_recipe_module_module(path, UniverseView(self, package))
      except (LoaderError,AssertionError,ImportError) as e:
        _amend_exception(e, 'while loading recipe module %s' % path)

      self._loaded[key] = mod
      return mod

  def loop_over_recipe_modules(self):
    """Yields pairs (package, module path)."""
    for package in self.packages:
      for path in package.module_dirs:
        if os.path.isdir(path):
          for item in os.listdir(path):
            subpath = os.path.join(path, item)
            if _is_recipe_module_dir(subpath):
              yield package, os.path.basename(subpath)


class UniverseView(collections.namedtuple('UniverseView', 'universe package')):
  """A UniverseView is a way of viewing a RecipeUniverse, as seen by a package.

  This is used mainly for dependency loading -- a package can only see modules
  in itself and packages that it directly depends on.
  """
  def _dep_from_name(self, name):
    if '/' in name:
      package, module = name.split('/')
      return self.package.find_dep(package), module
    else:
      # In current package
      return self.package, name

  def deps_from_spec(self, spec):
    """Load dependencies from a dependency spec.

    A dependency spec can either be a list of dependencies, such as:

    [ 'chromium', 'recipe_engine/step' ]

    Or a dictionary of dependencies with local names:

    {
      'chromium': 'build/chromium',
      'chromiuminternal': 'build_internal/chromium',
    }
    """

    # Automatic local names.
    if isinstance(spec, (list, tuple)):
      deps = {}
      for item in spec:
        package, name = self._dep_from_name(item)
        assert name not in deps, (
            "You specified two dependencies with the name %s" % name)
        deps[name] = self.universe.load(package, name)
    # Explicit local names.
    elif isinstance(spec, dict):
      deps = {}
      for name, item in spec.iteritems():
        package, dep_real_name = self._dep_from_name(item)
        deps[name] = self.universe.load(package, dep_real_name)
    return deps

  def load_recipe(self, recipe):
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
    # TODO(martiniss) change "infra/example" to ["infra", "example"], and handle
    # appropriately, because of windows.
    try:
      if ':' in recipe:
        module_name, example = recipe.split(':')
        #TODO(martinis) change to example == 'example' ? Technically a bug...
        assert example.endswith('example')
        for module_dir in self.package.module_dirs:
          subpath = os.path.join(module_dir, module_name)
          if not _is_recipe_module_dir(subpath):
            continue

          return RecipeScript.from_script_path(
              os.path.join(subpath, 'example.py'), self)
      else:
        for recipe_dir in self.package.recipe_dirs:
          recipe_path = os.path.join(recipe_dir, recipe)
          if os.path.exists(recipe_path + '.py'):
            return RecipeScript.from_script_path(recipe_path + '.py', self)

    except (LoaderError,AssertionError,ImportError) as e:
      _amend_exception(e, 'while loading recipe %s' % recipe)

    raise NoSuchRecipe(recipe)

  @property
  def module_dirs(self):
    for module_dir in self.package.module_dirs:
      yield module_dir

  @property
  def recipe_dirs(self):
    for recipe_dir in self.package.recipe_dirs:
      yield recipe_dir

  def loop_over_recipes(self):
    """Yields pairs (path to recipe, recipe name).

    Enumerates real recipes in recipes/*, as well as examples in
    recipe_modules/*.
    """
    for path in self.package.recipe_dirs:
      for recipe in scan_directory(
          path, lambda f: f.endswith('.py') and f[0] != '_'):
        yield recipe, recipe[len(path)+1:-len('.py')]
    for path in self.package.module_dirs:
      for recipe in scan_directory(
          path, lambda f: f.endswith('example.py')):
        module_name = os.path.dirname(recipe)[len(path)+1:]
        yield recipe, '%s:example' % module_name

  def loop_over_recipe_modules(self):
    """Yields the paths to all the modules that this view can see."""
    for path in self.package.module_dirs:
      if os.path.isdir(path):
        for item in os.listdir(path):
          subpath = os.path.join(path, item)
          if _is_recipe_module_dir(subpath):
            yield os.path.basename(subpath)


def _amend_exception(e, amendment):
  """Re-raise an exception e, appending amendment to the end of the message."""
  raise type(e), type(e)(e.message + '\n' + amendment), sys.exc_info()[2]


def _is_recipe_module_dir(path):
  return (os.path.isdir(path) and
          os.path.isfile(os.path.join(path, '__init__.py')))


def _find_and_load_module(fullname, modname, path):
  imp.acquire_lock()
  try:
    if fullname not in sys.modules:
      fil = None
      try:
        fil, pathname, descr = imp.find_module(modname,
                                               [os.path.dirname(path)])
        imp.load_module(fullname, fil, pathname, descr)
      finally:
        if fil:
          fil.close()
    return sys.modules[fullname]
  finally:
    imp.release_lock()


def _load_recipe_module_module(path, universe_view):
  modname = os.path.splitext(os.path.basename(path))[0]
  fullname = '%s.%s.%s' % (
      RECIPE_MODULE_PREFIX, universe_view.package.name, modname)
  mod = _find_and_load_module(fullname, modname, path)

  # This actually loads the dependencies.
  mod.LOADED_DEPS = universe_view.deps_from_spec(getattr(mod, 'DEPS', []))

  # Prevent any modules that mess with sys.path from leaking.
  with env.temp_sys_path():
    sys.modules['%s.DEPS' % fullname] = mod.LOADED_DEPS
    _recursive_import(
        path, '%s.%s' % (RECIPE_MODULE_PREFIX, universe_view.package.name))
    _patchup_module(modname, mod, universe_view)

  return mod


def _recursive_import(path, prefix):
  modname = os.path.splitext(os.path.basename(path))[0]
  fullname = '%s.%s' % (prefix, modname)
  mod = _find_and_load_module(fullname, modname, path)
  if not os.path.isdir(path):
    return mod

  for subitem in os.listdir(path):
    subpath = os.path.join(path, subitem)
    subname = os.path.splitext(subitem)[0]
    if os.path.isdir(subpath):
      if not os.path.exists(os.path.join(subpath, '__init__.py')):
        continue
    elif not subpath.endswith('.py') or subitem.startswith('__init__.py'):
      continue

    submod = _recursive_import(subpath, fullname)

    if not hasattr(mod, subname):
      setattr(mod, subname, submod)
    else:
      prev = getattr(mod, subname)
      assert submod is prev, (
        'Conflicting modules: %s and %s' % (prev, mod))

  return mod


def _patchup_module(name, submod, universe_view):
  """Finds framework related classes and functions in a |submod| and adds
  them to |submod| as top level constants with well known names such as
  API, CONFIG_CTX, TEST_API, and PROPERTIES.

  |submod| is a recipe module (akin to python package) with submodules such as
  'api', 'config', 'test_api'. This function scans through dicts of that
  submodules to find subclasses of RecipeApi, RecipeTestApi, etc.
  """
  fullname = '%s/%s' % (universe_view.package.name, name)
  submod.NAME = name
  submod.UNIQUE_NAME = fullname
  submod.MODULE_DIRECTORY = Path(ModuleBasePath(submod))
  submod.PACKAGE_REPO_ROOT = Path(PackageRepoBasePath(universe_view.package))
  submod.CONFIG_CTX = getattr(submod, 'CONFIG_CTX', None)

  if hasattr(submod, 'config'):
    for v in submod.config.__dict__.itervalues():
      if isinstance(v, ConfigContext):
        assert not submod.CONFIG_CTX, (
          'More than one configuration context: %s, %s' %
          (submod.config, submod.CONFIG_CTX))
        submod.CONFIG_CTX = v
    assert submod.CONFIG_CTX, 'Config file, but no config context?'

  submod.API = getattr(submod, 'API', None)
  for v in submod.api.__dict__.itervalues():
    if inspect.isclass(v) and issubclass(v, RecipeApiPlain):
      assert not submod.API, (
        '%s has more than one Api subclass: %s, %s' % (name, v, submod.API))
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

  # Let each property object know about the property name.
  submod.PROPERTIES = {
      prop_name: value.bind(prop_name, BoundProperty.MODULE_PROPERTY, name)
      for prop_name, value in getattr(submod, 'PROPERTIES', {}).items()}


class DependencyMapper(object):
  """DependencyMapper topologically traverses the dependency DAG beginning at
  a module, executing a callback ("instantiator") for each module.

  For example, if the dependency DAG looked like this:

          A
         / \
        B   C
         \ /
          D

  (with D depending on B and C, etc.), DependencyMapper(f).instantiate(D) would
  construct

  f_A = f(A, {})
  f_B = f(B, { 'A': f_A })
  f_C = f(C, { 'A': f_A })
  f_D = f(D, { 'B': f_B, 'C': f_C })

  finally returning f_D.  instantiate can be called multiple times, which reuses
  already-computed results.
  """

  def __init__(self, instantiator):
    self._instantiator = instantiator
    self._instances = {}

  def instantiate(self, mod):
    if mod in self._instances:
      return self._instances[mod]
    deps_dict = { name: self.instantiate(dep)
                  for name, dep in mod.LOADED_DEPS.iteritems() }
    self._instances[mod] = self._instantiator(mod, deps_dict)
    return self._instances[mod]


def _invoke_with_properties(callable_obj, all_props, prop_defs, arg_names,
                            **additional_args):
  """Internal version of invoke_with_properties.

  The main difference is it gets passed the argument names as `arg_names`.
  This allows us to reuse this logic elsewhere, without defining a fake function
  which has arbitrary argument names.
  """
  for name, prop in prop_defs.items():
    if not isinstance(prop, BoundProperty):
      raise ValueError(
          "You tried to invoke {} with an unbound Property {} named {}".format(
              callable, prop, name))

  # Maps parameter names to property names
  param_name_mapping = {
              prop.param_name: name for name, prop in prop_defs.iteritems()}

  props = []

  for param_name in arg_names:
    if param_name in additional_args:
      props.append(additional_args.pop(param_name))
      continue

    if param_name not in param_name_mapping:
      raise UndefinedPropertyException(
        "Missing property definition for parameter '{}'.".format(param_name))

    prop_name = param_name_mapping[param_name]

    if prop_name not in prop_defs:
      raise UndefinedPropertyException(
        "Missing property value for '{}'.".format(prop_name))

    prop = prop_defs[prop_name]
    props.append(prop.interpret(all_props.get(
      prop_name, PROPERTY_SENTINEL)))

  return callable_obj(*props, **additional_args)


def invoke_with_properties(callable_obj, all_props, prop_defs,
                           **additional_args):
  """
  Invokes callable with filtered, type-checked properties.

  Args:
    callable_obj: The function to call, or class to instantiate.
                  This supports passing in either RunSteps, or a recipe module,
                  which is a class.
    all_props: A dictionary containing all the properties (strings) currently
               defined in the system.
    prop_defs: A dictionary of property name to property definitions
               (BoundProperty) for this callable.
    additional_args: kwargs to pass through to the callable.
                     Note that the names of the arguments can correspond to
                     positional arguments as well.

  Returns:
    The result of calling callable with the filtered properties
    and additional arguments.
  """
  # Check that we got passed BoundProperties, and not Properties


  # To detect when they didn't specify a property that they have as a
  # function argument, list the arguments, through inspection,
  # and then comparing this list to the provided properties. We use a list
  # instead of a dict because getargspec returns a list which we would have to
  # convert to a dictionary, and the benefit of the dictionary is pretty small.
  if inspect.isclass(callable_obj):
    arg_names = inspect.getargspec(callable_obj.__init__).args

    arg_names.pop(0)
  else:
    arg_names = inspect.getargspec(callable_obj).args
  return _invoke_with_properties(callable_obj, all_props, prop_defs, arg_names,
                                 **additional_args)


def create_recipe_api(toplevel_deps, engine, test_data=DisabledTestData()):
  def instantiator(mod, deps):
    kwargs = {
      'module': mod,
      'engine': engine,
      # TODO(luqui): test_data will need to use canonical unique names.
      'test_data': test_data.get_module_test_data(mod.NAME)
    }
    prop_defs = mod.PROPERTIES
    mod_api = invoke_with_properties(
      mod.API, engine.properties, prop_defs, **kwargs)
    mod_api.test_api = (getattr(mod, 'TEST_API', None)
                        or RecipeTestApi)(module=mod)
    for k, v in deps.iteritems():
      setattr(mod_api.m, k, v)
      setattr(mod_api.test_api.m, k, v.test_api)
    mod_api.initialize()
    return mod_api

  mapper = DependencyMapper(instantiator)
  api = RecipeScriptApi(module=None, engine=engine,
                  test_data=test_data.get_module_test_data(None))
  for k, v in toplevel_deps.iteritems():
    setattr(api, k, mapper.instantiate(v))
  return api


def create_test_api(toplevel_deps, universe):
  def instantiator(mod, deps):
    modapi = (getattr(mod, 'TEST_API', None) or RecipeTestApi)(module=mod)
    for k,v in deps.iteritems():
      setattr(modapi.m, k, v)
    return modapi

  mapper = DependencyMapper(instantiator)
  api = RecipeTestApi(module=None)
  for k,v in toplevel_deps.iteritems():
    setattr(api, k, mapper.instantiate(v))
  return api
