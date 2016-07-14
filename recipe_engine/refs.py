# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

from . import loader


def main(universe, own_package, modules, transitive):
  result_modules = set()
  result_recipes = set()

  module_dependencies = {}

  for package, module_name in universe.loop_over_recipe_modules():
    mod = universe.load(package, module_name)
    module_dependencies[mod.NAME] = mod.LOADED_DEPS

    for module in modules:
      if module in mod.LOADED_DEPS:
        result_modules.add(mod.NAME)
        break

  if transitive:
    queue = list(result_modules)
    while queue:
      module = queue.pop()
      for iter_module, deps in module_dependencies.iteritems():
        if iter_module in result_modules:
          continue
        if module in deps:
          result_modules.add(iter_module)
          queue.append(iter_module)

  universe_view = loader.UniverseView(universe, own_package)
  for _, recipe_name in universe_view.loop_over_recipes():
    recipe = universe_view.load_recipe(recipe_name)

    for module in modules + (list(result_modules) if transitive else []):
      if module in recipe.LOADED_DEPS:
        result_recipes.add(recipe_name)

  if result_modules:
    print('Modules:')
    for module in sorted(result_modules):
      print('  %s' % module)

  if result_recipes:
    print('Recipes:')
    for recipe in sorted(result_recipes):
      print('  %s' % recipe)
