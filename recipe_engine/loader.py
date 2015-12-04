# Copyright 2013-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import contextlib
import imp
import inspect
import os
import sys

from .config import ConfigContext, ConfigGroupSchema
from .config_types import Path, ModuleBasePath, PackageBasePath
from .config_types import RECIPE_MODULE_PREFIX
from .recipe_api import RecipeApi, RecipeApiPlain, RecipeScriptApi
from .recipe_api import Property, BoundProperty
from .recipe_api import UndefinedPropertyException, PROPERTY_SENTINEL
from .recipe_test_api import RecipeTestApi, DisabledTestData
from .util import scan_directory


class NoSuchRecipe(Exception):
  """Raised by load_recipe is recipe is not found."""


class RecipeScript(object):
  """Holds dict of an evaluated recipe script."""

  def __init__(self, recipe_dict, name):
    self.name = name

    # Let each property object know about the property name.
    recipe_dict['PROPERTIES'] = {
        name: value.bind(name, BoundProperty.RECIPE_PROPERTY, name)
        for name, value in recipe_dict.get('PROPERTIES', {}).items()}

    return_schema = recipe_dict.get('RETURN_SCHEMA')
    if return_schema and not isinstance(return_schema, ConfigGroupSchema):
      raise ValueError("Invalid RETURN_SCHEMA; must be an instance of \
                       ConfigGroupSchema")

    for k, v in recipe_dict.iteritems():
      setattr(self, k, v)

  def run(self, api, properties):
    """
    Run this recipe, with the given api and property arguments.
    Check the return value, if we have a RETURN_SCHEMA.
    """
    recipe_result = invoke_with_properties(
      self.RunSteps, properties, self.PROPERTIES, api=api)

    return_schema = getattr(self, 'RETURN_SCHEMA', None)

    if return_schema:
      if not recipe_result:
        raise ValueError("Recipe %s did not return a value." % self.name)
      return recipe_result.as_jsonish(True)
    else:
      return None

  @classmethod
  def from_script_path(cls, script_path, universe_view):
    """Evaluates a script and returns RecipeScript instance."""

    script_vars = {}
    script_vars['__file__'] = script_path

    with _preserve_path():
      execfile(script_path, script_vars)

    script_vars['LOADED_DEPS'] = universe_view.deps_from_spec(
        script_vars.get('DEPS', []))

    # 'a/b/c/my_name.py' -> my_name
    name = os.path.basename(script_path).split('.')[0]
    return cls(script_vars, name)


class Dependency(object):
  def load(self, universe):
    raise NotImplementedError()

  @property
  def local_name(self):
    raise NotImplementedError()

  @property
  def unique_name(self):
    """A unique identifier for the module that this dependency refers to.
    This must be generated without loading the module."""
    raise NotImplementedError()


class PathDependency(Dependency):
  def __init__(self, path, local_name, load_from_package, universe):
    assert os.path.isabs(path), (
        'Path dependencies must be absolute, but %s is not' % path)
    self._path = path
    self._local_name = local_name
    self._load_from_package = load_from_package

    # We forbid modules from living outside our main paths to keep clients
    # from going crazy before we have standardized recipe locations.
    mod_dir = os.path.dirname(path)
    assert mod_dir in universe.module_dirs, (
      'Modules living outside of approved directories are forbidden: '
      '%s is not in %s' % (mod_dir, universe.module_dirs))

  def load(self, universe):
    try:
      return _load_recipe_module_module(
          self._path, UniverseView(universe, self._load_from_package))
    except Exception as e:
      _amend_exception(e, 'while loading recipe module %s' % self._path)


  @property
  def local_name(self):
    return self._local_name

  @property
  def unique_name(self):
    return self._path


class NamedDependency(PathDependency):
  def __init__(self, name, universe_view):
    for path in universe_view.package.module_dirs:
      mod_path = os.path.join(path, name)
      if _is_recipe_module_dir(mod_path):
        super(NamedDependency, self).__init__(
            mod_path, name, universe=universe_view.universe,
            load_from_package=universe_view.package)
        return
    raise NoSuchRecipe('Recipe module named %s does not exist' % name)


class PackageDependency(PathDependency):
  def __init__(self, package_name, module_name, local_name, universe_view):
    load_from_package = universe_view.package.find_dep(package_name)
    mod_path = load_from_package.module_path(module_name)
    super(PackageDependency, self).__init__(
        mod_path, local_name, universe=universe_view.universe,
        load_from_package=load_from_package)


class RecipeUniverse(object):
  def __init__(self, package_deps, config_file):
    self._loaded = {}
    self._package_deps = package_deps
    self._config_file = config_file

  @property
  def config_file(self):
    return self._config_file

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
  def package_deps(self):
    return self._package_deps

  def load(self, dep):
    """Load a Dependency."""
    name = dep.unique_name
    if name in self._loaded:
      mod = self._loaded[name]
      assert mod is not None, (
          'Cyclic dependency when trying to load %s' % name)
      return mod
    else:
      self._loaded[name] = None
      mod = dep.load(self)
      self._loaded[name] = mod
      return mod

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
    try:
      if ':' in recipe:
        module_name, example = recipe.split(':')
        assert example.endswith('example')
        for package in self.package_deps.packages:
          for module_dir in package.module_dirs:
            if os.path.isdir(module_dir):
              for subitem in os.listdir(module_dir):
                if module_name == subitem:
                  return RecipeScript.from_script_path(
                      os.path.join(module_dir, subitem, 'example.py'),
                      UniverseView(self, package))
        raise NoSuchRecipe(recipe,
                           'Recipe example %s:%s does not exist' %
                           (module_name, example))
      else:
        for package in self.package_deps.packages:
          for recipe_dir in package.recipe_dirs:
            recipe_path = os.path.join(recipe_dir, recipe)
            if os.path.exists(recipe_path + '.py'):
              return RecipeScript.from_script_path(recipe_path + '.py',
                                                   UniverseView(self, package))
    except Exception as e:
      _amend_exception(e, 'while loading recipe %s' % recipe)

    raise NoSuchRecipe(recipe)

  def loop_over_recipe_modules(self):
    """Yields pairs (package, module path)."""
    for package in self.package_deps.packages:
      for path in package.module_dirs:
        if os.path.isdir(path):
          for item in os.listdir(path):
            subpath = os.path.join(path, item)
            if _is_recipe_module_dir(subpath):
              yield package, subpath

  def loop_over_recipes(self):
    """Yields pairs (path to recipe, recipe name).

    Enumerates real recipes in recipes/* as well as examples in recipe_modules/*.
    """
    for path in self.recipe_dirs:
      for recipe in scan_directory(
          path, lambda f: f.endswith('.py') and f[0] != '_'):
        yield recipe, recipe[len(path)+1:-len('.py')]
    for path in self.module_dirs:
      for recipe in scan_directory(
          path, lambda f: f.endswith('example.py')):
        module_name = os.path.dirname(recipe)[len(path)+1:]
        yield recipe, '%s:example' % module_name


class UniverseView(collections.namedtuple('UniverseView', 'universe package')):
  """A UniverseView is a way of viewing a RecipeUniverse, as seen by a package.

  This is used mainly for dependency loading -- a package can only see modules
  in itself and packages that it directly depends on.
  """
  def _dep_from_name(self, name):
    if '/' in name:
      [package,module] = name.split('/')
      dep = PackageDependency(package, module, module, universe_view=self)
    else:
      # In current package
      module = name
      dep = NamedDependency(name, universe_view=self)

    return module, dep

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
        name, dep = self._dep_from_name(item)
        deps[name] = self.universe.load(dep)
    # Explicit local names.
    elif isinstance(spec, dict):
      deps = {}
      for name, item in spec.iteritems():
        _, dep = self._dep_from_name(item)
        deps[name] = self.universe.load(dep)
    return deps


def _amend_exception(e, amendment):
  """Re-raise an exception e, appending amendment to the end of the message."""
  raise type(e), type(e)(e.message + '\n' + amendment), sys.exc_info()[2]


def _is_recipe_module_dir(path):
  return (os.path.isdir(path) and
          os.path.isfile(os.path.join(path, '__init__.py')))


@contextlib.contextmanager
def _preserve_path():
  old_path = sys.path[:]
  try:
    yield
  finally:
    sys.path = old_path


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
  fullname = '%s.%s' % (RECIPE_MODULE_PREFIX, modname)
  mod = _find_and_load_module(fullname, modname, path)

  # This actually loads the dependencies.
  mod.LOADED_DEPS = universe_view.deps_from_spec(getattr(mod, 'DEPS', []))

  # Prevent any modules that mess with sys.path from leaking.
  with _preserve_path():
    # TODO(luqui): Remove this hack once configs are cleaned.
    sys.modules['%s.DEPS' % fullname] = mod.LOADED_DEPS
    _recursive_import(path, RECIPE_MODULE_PREFIX)
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
  submod.NAME = name
  submod.UNIQUE_NAME = name  # TODO(luqui): use a luci-config unique name
  submod.MODULE_DIRECTORY = Path(ModuleBasePath(submod))
  submod.PACKAGE_DIRECTORY = Path(PackageBasePath(universe_view.package))
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
        '%s has more than one Api subclass: %s, %s' % (name, v, submod.api))
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

  props = []
  for arg in arg_names:
    if arg in additional_args:
      props.append(additional_args.pop(arg))
      continue

    if arg not in prop_defs:
      raise UndefinedPropertyException(
        "Missing property definition for '{}'.".format(arg))

    prop = prop_defs[arg]
    props.append(prop.interpret(all_props.get(
      prop.param_name, PROPERTY_SENTINEL)))

  return callable_obj(*props, **additional_args)

def invoke_with_properties(callable_obj, all_props, prop_defs,
                           **additional_args):
  """
  Invokes callable with filtered, type-checked properties.

  Args:
    callable_obj: The function to call, or class to instantiate.
                  This supports passing in either RunSteps, or a recipe module,
                  which is a class.
    all_props: A dictionary containing all the properties (instances of BoundProperty)
               currently defined in the system.
    prop_defs: A dictionary of name to property definitions for this callable.
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
