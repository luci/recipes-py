# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import collections
import json
import os
import subprocess
import sys

from . import loader
from . import env

import argparse  # this is vendored

from . import analyze_pb2
from google.protobuf import json_format as jsonpb

GIT = 'git.bat' if sys.platform == 'win32' else 'git'


def add_subparser(parser):
  help_str = ('Calculates the affected recipes from a set of modified files.'
              ' Useful for triggering additional testing based on e.eg patches'
              ' to the recipes.')
  analyze_p = parser.add_parser(
    'analyze',
    help=help_str,
    description=help_str)
  analyze_p.add_argument(
    'input', type=argparse.FileType('r'),
    help='Path to a JSON object. Valid fields: "files", "recipes". See'
         ' analyze.proto file for more information')
  analyze_p.add_argument(
    'output', type=argparse.FileType('w'), default=sys.stdout,
    help='The file to write output to. See analyze.proto for more information.')
  analyze_p.set_defaults(func=main)


def get_git_attribute_files(repo_root):
  """Returns the files referenced from repo's .gitattribute file.

  Args:
    * repo_root: The path to the root of a repo.
  """
  args = [
    GIT, '-C', repo_root, 'ls-files', '--',
    ':(attr:recipes)',
  ]
  return [
      os.path.join(repo_root, path) for path in
      subprocess.check_output(args).splitlines()]


def get_id_tuple(mod, universe):
  """Returns a tuple of (package, module name). Used as a key to do BFS.

  Args:
    * mod: module object, as read through loader.py.
    * universe: An instance of RecipeUniverse.
  """
  return (universe.package_deps.get_package(
      mod.UNIQUE_NAME.split('/')[0]), mod.NAME)


def analyze(universe, in_data):
  """Determine which recipes are affected by a list of files.

  Args:
    * universe: An instance of loader.RecipeUniverse.
    * in_data: An instance of analyze_pb2.Input.

  Returns:
    An instance of analyze_pb2.Output, representing the result of the analysis.
  """
  output = analyze_pb2.Output()

  if not in_data.recipes:
    output.error = 'Must provide a set of recipes as input'
    return output

  # Make sure files are all absolute.
  for i, fname in enumerate(in_data.files):
    if not os.path.isabs(fname):
      in_data.files[i] = os.path.join(
          universe.package_deps.root_package.repo_root, fname)

  # Get a list of all recipes, and validate the recipes input
  universe_view = loader.UniverseView(
      universe, universe.package_deps.root_package)
  all_recipes = set(
      recipe_name for (_, recipe_name) in universe_view.loop_over_recipes())
  output.invalid_recipes.extend(list(set(in_data.recipes) - all_recipes))
  if output.invalid_recipes:
    output.error = 'Some input recipes were invalid'
  valid_recipes = set(in_data.recipes) - set(output.invalid_recipes)

  # Used to look at git attributes later. Maps package name to the contents of
  # its .gitattributes file. Mainly a cache so we only read the file once.
  git_attr_file_map = {}

  # We look at 3 different sets of files which could affect the recipe.
  for recipe in valid_recipes:
    # 1: The recipes themselves.
    loaded_recipe = universe_view.load_recipe(recipe)
    if set(in_data.files).intersection([loaded_recipe.path]):
      output.recipes.append(recipe)
      continue

    # 2: The modules.
    queue = [get_id_tuple(
        mod, universe) for mod in loaded_recipe.LOADED_DEPS.values()]

    # Do a Breadth First Search of all the modules this recipe transitively
    # depends on.
    while queue:
      pkg, module_name = queue.pop()

      mod = universe.load(pkg, module_name)
      # We depend on MODULE_DIRECTORY not having any path pieces
      mod_path = mod.MODULE_DIRECTORY.base.resolve(False)
      if any(fname.startswith(mod_path) for fname in in_data.files):
        output.recipes.append(recipe)
        break

      # 3: Git attribute files, declared in .gitattribute in the root of the
      # repo.
      if pkg.name not in git_attr_file_map:
        git_attr_file_map[pkg.name] = set(get_git_attribute_files(
            universe.package_deps.get_package(pkg.name).repo_root))
      if set(in_data.files).intersection(git_attr_file_map[pkg.name]):
        output.recipes.append(recipe)
        break

      for dep in mod.LOADED_DEPS.values():
        queue.append(get_id_tuple(dep, universe))

  return output


def main(package_deps, args):
  universe = loader.RecipeUniverse(package_deps, args.package)
  in_data = jsonpb.Parse(args.input.read(), analyze_pb2.Input())
  args.input.close()

  data = analyze(universe, in_data)
  args.output.write(jsonpb.MessageToJson(
      data, including_default_value_fields=True))
  return bool(data.error)
