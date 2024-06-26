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
import os
import sys


class RecipeModuleImporter:
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

    mod.__dict__.update(loaded.__dict__)
    return mod
