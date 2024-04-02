# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys

from gevent import subprocess

from google.protobuf import json_format as jsonpb

from PB.recipe_engine.analyze import Input, Output

GIT = 'git.bat' if sys.platform == 'win32' else 'git'


def get_git_attribute_files(repo_root):
  """Returns the files referenced from repo's .gitattribute file.

  TODO(iannucci): Move this functionality to fetch.GitBackend
  TODO(iannucci): Allow this to work correctly for non-git backed repos (e.g.
    bundled recipes)

  Args:
    * repo_root: The path to the root of a repo.
  """
  args = [
    GIT, '-C', repo_root, 'ls-files', '--',
    ':(attr:recipes)',
  ]
  return [
      os.path.join(repo_root, path) for path in
      subprocess.check_output(args, text=True).splitlines()]


def analyze(recipe_deps, in_data):
  """Determine which recipes are affected by a list of files.

  Args:
    * recipe_deps (RecipeDeps) - All the loaded recipe repos.
    * in_data (analyze_pb2.Input) - The input parameters for the analysis.

  Returns an instance of analyze_pb2.Output, representing the result of the
  analysis.
  """
  output = Output()

  if not in_data.recipes:
    output.error = 'Must provide a set of recipes as input'
    return output

  main_repo = recipe_deps.main_repo

  # Make sure files are all absolute.
  for i, fname in enumerate(in_data.files):
    if not os.path.isabs(fname):
      in_data.files[i] = os.path.join(main_repo.path, fname)

  all_recipe_names = set(main_repo.recipes)
  output.invalid_recipes.extend(list(set(in_data.recipes) - all_recipe_names))
  if output.invalid_recipes:
    output.error = 'Some input recipes were invalid'
  valid_recipes = set(in_data.recipes) - set(output.invalid_recipes)

  # Used to look at git attributes later. Maps repo_name to the contents of
  # its .gitattributes file. Mainly a cache so we only read the file once.
  git_attr_file_map = {}

  # We look at 4 different sets of files which could affect the recipe.
  for recipe_name in (r for r in in_data.recipes if r in valid_recipes):
    # 1: The recipes themselves.
    recipe = main_repo.recipes[recipe_name]
    isect = set(in_data.files).intersection([recipe.path])
    if isect:
      print(
          'Adding %r to output set; recipe is directly modified: %r'
          % (recipe_name, sorted(isect)), file=sys.stderr)
      output.recipes.append(recipe_name)
      continue

    # 2: The recipes' resource files.
    affected_resources = sorted(
        fname for fname in in_data.files
        if fname.startswith(recipe.resources_dir + os.path.sep)
    )
    if affected_resources:
      print(
          'Adding %r to output set; resource files modified: %r'
          % (recipe_name, affected_resources), file=sys.stderr)
      output.recipes.append(recipe_name)
      continue

    # 3: The modules. This is the list of (repo_name, module_name)
    queue = set(recipe.normalized_DEPS.values())

    processed = set()

    # Do a Breadth First Search of all the modules this recipe transitively
    # depends on.
    while queue:
      repo_name, module_name = queue.pop()
      mod = recipe_deps.repos[repo_name].modules[module_name]

      # Any file inside this module modified?
      isect = set()
      for fname in in_data.files:
        if fname.startswith(mod.path + os.path.sep):
          isect.add(fname)
      if isect:
        print(
            'Adding %r to output set; recipe module dep %r is modified: %r'
            % (recipe_name, mod.name, sorted(isect)), file=sys.stderr)
        output.recipes.append(recipe_name)
        break

      # 4: Git attribute files, declared in .gitattribute in the root of the
      # repo.
      if repo_name not in git_attr_file_map:
        git_attr_file_map[repo_name] = set(
          get_git_attribute_files(recipe_deps.repos[repo_name].path))
      isect = set(in_data.files).intersection(git_attr_file_map[repo_name])
      if isect:
        print(
            'Adding %r to output set; gitattrs overlaps with input files: %r'
            % (recipe_name, sorted(isect)), file=sys.stderr)
        output.recipes.append(recipe_name)
        break

      # We've now processed this module, so add it to 'processed' so we don't
      # process it again.
      processed.add((repo_name, module_name))

      # Add any DEPS that this module has to the queue, except for anything
      # we've processed already.
      queue |= set(mod.normalized_DEPS.values()) - processed

  return output


def main(args):
  in_data = jsonpb.Parse(args.input.read(), Input())
  args.input.close()

  data = analyze(args.recipe_deps, in_data)
  args.output.write(jsonpb.MessageToJson(
      data, including_default_value_fields=True))
  return bool(data.error)
