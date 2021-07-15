# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This file implements a PEP302-style import hook which makes the
`RECIPE_MODULES` python module space importable.

Usage:

    sys.meta_path.append(RecipeModuleImporter(recipe_deps))

    # Accesses /$recipe_engine/recipe_modules/path/* python files
    from RECIPE_MODULES.recipe_engine import path
    from RECIPE_MODULES.recipe_engine.path import config

Read PEP302 for the full description of how this works, but the short version is
that an import hook implements:
  * find_module(name): returns an object with `.load_module` (possibly self) if
    this hook knows how to load `name`. Otherwise returns None.
  * load_module(name): returns a loaded python module object for name.

There are some subtleties here like:
  * python will try find_module('module.name.os') when 'module.name' tries to
    `import os`
  * The __package__ metavar (set in load_module) is important to let python know
    "this module may have submodules in it". Otherwise if this is not set then
    python will assume that the module is from some .py file, and so cannot
    have submodules.
  * Once a module is loaded (e.g. 'foo.bar'), it's cached in `sys.modules`. The
    import hook is only used when the module has not yet been loaded. Further
    imports of the same module get the cached version.
    * ... except with reload() which jacks up everything.
"""


import imp
import importlib
import inspect
import os
import sys

from future.utils import iteritems, itervalues

from ..config_types import Path, ModuleBasePath, RepoBasePath
from ..recipe_api import BoundProperty, RecipeApi, RecipeApiPlain
from ..recipe_test_api import RecipeTestApi

from . import proto_support


class RecipeModuleImporter(object):
  """This implements both the `find_module` and `load_module` halves of the
  import hook protocol.

  It uses a RecipeDeps object as the source of truth for what repos and modules
  are actually available.
  """

  PREFIX = 'RECIPE_MODULES'

  def __init__(self, recipe_deps):
    self._recipe_deps = recipe_deps

  def find_module(self, fullname, path=None):  # pylint: disable=unused-argument
    if fullname == self.PREFIX or fullname.startswith(self.PREFIX + '.'):
      toks = fullname.split('.')
      if 1 <= len(toks) <= 3:
        # We should definitely handle all of these.
        # RECIPE_MODULES
        # RECIPE_MODULES.<repo_name>
        # RECIPE_MODULES.<repo_name>.<module_name>
        return self
      if len(toks) > 3:
        # We can only be guaranteed to handle this if such a file exists.
        #
        # For example, if api.py in a module does `import base64`, python will
        # first try:
        #
        #   RECIPE_MODULES.<repo_name>.<module_name>.base64
        #
        # So we should only return ourselves as a loader if we can ACTUALLY
        # import the requested module.
        repo_name = toks[1]
        module_name = toks[2]
        mod_dir = self._recipe_deps.repos[repo_name].modules[module_name].path
        target = os.path.join(mod_dir, *toks[3:])
        if (os.path.isdir(target) and
            os.path.isfile(os.path.join(target, '__init__.py'))):
          # This is a module in the recipe package.
          return self
        elif os.path.isfile(target + '.py'):
          # This is a python file in the recipe package.
          return self

      # Otherwise, we'll have to let python resolve this along e.g. sys.path
      # and builtins.
      return None

  def load_module(self, fullname):
    """Returns:

      * `RECIPE_MODULES` module. This is an empty placeholder module.
      * `RECIPE_MODULES.repo_name` module. This is an empty placeholder module,
        but it has __path__ set to the `recipe_modules` path of the given repo.
      * `RECIPE_MODULES.repo_name.mod_name` module. This is the real python
        module (i.e. whatever is in this modules' __init__.py). Additionally
        this adds extra attributes (see _patchup_module).
      * `RECIPE_MODULES.repo_name.mod_name...` modules. These are the real
        python modules contained within 'repo_name/mod_name' without any tweaks.
    """


    # fullname is RECIPE_MODULES[.<repo_name>[.<mod_name>[.etc.etc]]]
    mod = sys.modules.setdefault(fullname, imp.new_module(fullname))
    mod.__loader__ = self
    toks = fullname.split('.')
    assert len(toks) > 0
    if len(toks) == 1:
      mod.__file__ = "<RecipeModuleImporter>"
      mod.__path__ = []
      mod.__package__ = fullname
      return mod

    repo_name = toks[1]
    repo = self._recipe_deps.repos[repo_name]
    if len(toks) == 2:
      mod.__file__ = repo.modules_dir
      mod.__path__ = [mod.__file__]
      mod.__package__ = fullname
      return mod

    # This is essentially a regular python module loader at this point, except
    # that:
    #   * The prefix of the module name is `RECIPE_MODULES.<repo_name>`.
    #   * The loader is scoped within the actual directory of the recipe module.
    #   * If it's exactly `RECIPE_MODULES.<repo_name>.<mod_name>`, then we also
    #     call _patchup_module on it.
    parent_mod_name, _, to_load = fullname.rpartition('.')
    # This imports the parent module. This doesn't devolve into recursive
    # madness because:
    #
    #   * Python always imports modules in order (i.e. 'a.b' comes before
    #    'a.b.c'.
    #   * Python caches imports in sys.modules (so this should always turn into
    #     a dictionary lookup in sys.modules).
    #
    # We don't just look up stuff in sys.modules because `importlib` is the
    # correct api for accessing modules.
    parent_mod = importlib.import_module(parent_mod_name)
    f, pathname, description = imp.find_module(to_load, parent_mod.__path__)
    loaded = imp.load_module(fullname, f, pathname, description)
    if f:
      f.close()
    if len(toks) == 3:  # RECIPE_MODULES.repo_name.module_name
      self._patchup_module(loaded, repo.path)

    mod.__dict__.update(loaded.__dict__)
    return mod

  @staticmethod
  def _patchup_module(mod, repo_root):
    """Adds a bunch of fields to the imported recipe module.

    TODO: most of these are obsolete and could be calculated at the sites that
    use them. At some point in the future we should remove _patchup_module
    entirely and rely on the builtin fields like __name__, __file__, etc. to
    calculate all these details.

    Currently sets the additional attributes on the python module:
      * `NAME`: The module's short name (e.g. 'path')
      * `API`: The class derived from RecipeApiPlain in api.py
      * `TEST_API`: The class derived from RecipeTestApi in test_api.py. If none
        exists, then this is set to RecipeTestApi.
      * `PROPERTIES`: A dictionary derived from 'PROPERTIES' defined in
        __init__.py, except that all of the Property values are 'bound' by
        calling their `bind()` method.
      * `MODULE_DIRECTORY`: The module's directory (as a Path object).
      * `RESOURCE_DIRECTORY`: The module's ./resource directory (as a Path
        object).
      * `REPO_ROOT`: A Path object for the root of the repo containing this
        module.
      * `CONFIG_CTX`: The ConfigContext object (defined in config.py) for this
        module, or None if no config.py exists.
      * `DEPS`: Sets a default DEPS value of `()` so that other code in the
        engine can assume that there's ALWAYS a DEPS object for a module.
      * `WARNINGS`: A list of warnings issued against this recipe module.
      * `DISABLE_STRICT_COVERAGE`: Sets a default value of False.
      * `PYTHON_VERSION_COMPATIBILITY`: "PY2", "PY2+3" or "PY3". Defaults to
        "PY2".

    Args:
      * mod (python module type) - This will be the module loaded for e.g.
        RECIPE_MODULES.repo_name.module_name.
      * repo_root (str) - Absolute path to the root of the module's repository
        on disk.
    """
    _, repo_name, module_name = mod.__name__.split('.')
    mod.NAME = module_name
    mod.MODULE_DIRECTORY = Path(ModuleBasePath(mod))
    mod.RESOURCE_DIRECTORY = mod.MODULE_DIRECTORY.join('resources')
    mod.REPO_ROOT = Path(RepoBasePath(repo_name, repo_root))
    mod.CONFIG_CTX = getattr(mod, 'CONFIG_CTX', None)
    mod.DEPS = getattr(mod, 'DEPS', ())
    mod.WARNINGS = getattr(mod, 'WARNINGS', ())

    # TODO(iannucci, probably): remove DISABLE_STRICT_COVERAGE (crbug/693058).
    mod.DISABLE_STRICT_COVERAGE = getattr(mod, 'DISABLE_STRICT_COVERAGE', False)

    mod.PYTHON_VERSION_COMPATIBILITY = getattr(
        mod, 'PYTHON_VERSION_COMPATIBILITY', 'PY2')

    # TODO(iannucci): do these imports on-demand at the callsites needing these.

    # NOTE: late import to avoid early protobuf import
    from ..config import ConfigContext

    cfg_module = None
    if os.path.isfile(os.path.join(mod.__path__[0], 'config.py')):
      cfg_module = importlib.import_module(mod.__name__ + '.config')

    if cfg_module:
      for v in itervalues(cfg_module.__dict__):
        if isinstance(v, ConfigContext):
          assert not mod.CONFIG_CTX, (
            'More than one configuration context: %s, %s' %
            (cfg_module, mod.CONFIG_CTX))
          mod.CONFIG_CTX = v
      assert mod.CONFIG_CTX, 'Config file, but no config context?'

    # The current config system relies on implicitly importing all the
    # *_config.py files... ugh.
    for fname in os.listdir(os.path.dirname(mod.__file__)):
      if fname.endswith('_config.py'):
        importlib.import_module(mod.__name__ + '.' + fname.rstrip('.py'))

    # Identify the RecipeApiPlain subclass as this module's API.
    mod.API = getattr(mod, 'API', None)

    api_module = importlib.import_module(mod.__name__ + '.api')

    for v in itervalues(api_module.__dict__):
      # If the recipe has literally imported the RecipeApi, we don't want to
      # consider that to be the real RecipeApi :)
      if v is RecipeApiPlain or v is RecipeApi:
        continue
      if inspect.isclass(v) and issubclass(v, RecipeApiPlain):
        assert not mod.API, (
          '%s has more than one RecipeApi subclass: %s, %s' % (
              module_name, v, mod.API))
        mod.API = v
    assert mod.API, 'Recipe module has no api? %s' % (mod,)

    # Identify the (optional) RecipeTestApi subclass as this module's test API.
    test_module = None
    if os.path.isfile(os.path.join(mod.__path__[0], 'test_api.py')):
      test_module = importlib.import_module(mod.__name__ + '.test_api')

    mod.TEST_API = getattr(mod, 'TEST_API', None)
    if test_module:
      for v in itervalues(mod.test_api.__dict__):
        # If the recipe has literally imported the RecipeTestApi, we don't want
        # to consider that to be the real RecipeTestApi :)
        if v is RecipeTestApi:
          continue
        if inspect.isclass(v) and issubclass(v, RecipeTestApi):
          assert not mod.TEST_API, (
            'More than one TestApi subclass: %s' % mod.api)
          mod.TEST_API = v
      assert mod.API, (
        'Recipe module has test_api.py but no TestApi subclass? %s' % (mod,))
    else:
      mod.TEST_API = RecipeTestApi

    properties_def = getattr(mod, 'PROPERTIES', {})

    # If PROPERTIES isn't a protobuf Message, it must be a legacy Property dict.
    if not proto_support.is_message_class(properties_def):
      # Let each property object know about the property name.
      full_decl_name = '%s::%s' % (repo_name, module_name)
      mod.PROPERTIES = {
          prop_name: value.bind(prop_name, BoundProperty.MODULE_PROPERTY,
                                full_decl_name)
          for prop_name, value in iteritems(properties_def)
      }
