# -*- coding: utf-8 -*-
# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function, absolute_import

import contextlib
import logging
import sys

from future.utils import itervalues

from google.protobuf import json_format as jsonpb

from PB.recipe_engine.internal.commands.deps import deps

from ...recipe_deps import RecipeDeps   # for type info
from ...exceptions import RecipeUsageError


def extract_module_names(obj):
  for repo, name in itervalues(obj.normalized_DEPS):
    yield '%s/%s' % (repo, name)


def py_compat(py_compat_str):
  if py_compat_str is None:
    return deps.CANNOT_RUN
  if py_compat_str == 'PY3':
    return deps.PYTHON3_ONLY
  if py_compat_str == 'PY2+3':
    return deps.PYTHON2_AND_PYTHON3
  return deps.PYTHON2_ONLY


def load_recipes_modules(rd, target, include_test_recipes, include_dependants):
  is_module = False
  if '::' in target:
    target_repo, target_name = target.split('::', 1)
  else:
    is_module = True
    target_repo, target_name = target.split('/', 1)
  if not target_repo:
    target_repo = rd.main_repo_id

  recipes = []
  mod_names = set()

  if not is_module:
    base = rd.repos[target_repo]
    if ':' in target_name:
      mod, target_name = target_name.split(':', 1)
      base = base.modules[mod]
    recipes.append(base.recipes[target_name])
  else:
    # Check that this module actually exists. This raises
    # UnknownRecipeModule if target_name doesn't exist.
    _ = rd.repos[target_repo].modules[target_name]
    mod_names.add('%s/%s' % (target_repo, target_name))

    if include_dependants:
      mod = (target_repo, target_name)
      for repo in rd.repos.values():
        if repo.name == target_repo or target_repo in repo.simple_cfg.deps:
          for recipe in repo.recipes.values():
            if (not include_test_recipes and (
                ':examples/' in recipe.name
                or ':tests/' in recipe.name)):
              continue

            if mod in itervalues(recipe.normalized_DEPS):
              recipes.append(recipe)

  for recipe in recipes:
    mod_names.update(extract_module_names(recipe))

  return recipes, mod_names


def process_modules(ret, rd, mod_names):
  processed_mod_names = set()
  while mod_names:
    full_mod_name = mod_names.pop()
    processed_mod_names.add(full_mod_name)

    repo, mod_name = full_mod_name.split('/', 1)
    mod = rd.repos[repo].modules[mod_name]

    mRecord = ret.modules[full_mod_name]
    mRecord.repo = repo
    mRecord.name = mod_name
    mRecord.claimed_py3_status = py_compat(mod.python_version_compatibility)
    mRecord.effective_py3_status = py_compat(mod.effective_python_compatility)

    mods = set(extract_module_names(mod))
    mRecord.deps.extend(mods)
    mod_names.update(mods - processed_mod_names)

    cfg = mod.repo.recipes_cfg_pb2
    if cfg.canonical_repo_url:
      mRecord.url = '%s/+/HEAD/%s' % (
        cfg.canonical_repo_url,
        mod.relpath,
      )


def process_recipes(ret, recipes):
  for recipe in recipes:
    rRecord = ret.recipes[recipe.full_name]
    rRecord.repo = recipe.repo.name
    rRecord.name = recipe.name
    rRecord.is_recipe = True
    rRecord.claimed_py3_status = py_compat(recipe.python_version_compatibility)
    rRecord.effective_py3_status = py_compat(recipe.effective_python_compatility)
    rRecord.deps.extend(extract_module_names(recipe))

    cfg = recipe.repo.recipes_cfg_pb2
    if cfg.canonical_repo_url:
      rRecord.url = '%s/+/HEAD/%s' % (
        cfg.canonical_repo_url,
        recipe.relpath,
      )


def output_cli(ret):
  to_emoji = {
    deps.CANNOT_RUN: '💀',
    deps.PYTHON2_ONLY: '❌',
    deps.PYTHON2_AND_PYTHON3: '✅',
    deps.PYTHON3_ONLY: '🦄',
  }

  print("recipes:")
  for _, recipe in sorted(ret.recipes.items()):
    print("  %s %s %s::%s - %s" % (
      to_emoji[recipe.claimed_py3_status],
      to_emoji[recipe.effective_py3_status],
      recipe.repo, recipe.name, recipe.url))

  print()
  print("modules:")
  for _, module in sorted(ret.modules.items()):
    print("  %s %s %s/%s - %s" % (
      to_emoji[module.claimed_py3_status],
      to_emoji[module.effective_py3_status],
      module.repo, module.name, module.url))


def output_json(fd, ret):
  fd.write(jsonpb.MessageToJson(
      ret,
      preserving_proto_field_name=True,
      indent=2, sort_keys=True,
  ))
  fd.write('\n')


def main(args):
  logging.basicConfig()

  rd = args.recipe_deps  # type: RecipeDeps

  try:
    recipes, mod_names = load_recipes_modules(
        rd, args.recipe_or_module, args.include_test_recipes,
        args.include_dependants)
  except RecipeUsageError as ex:
    print('{}: {}'.format(type(ex).__name__, ex), file=sys.stderr)
    return 1

  ret = deps.Deps()

  process_recipes(ret, recipes)
  process_modules(ret, rd, mod_names)

  if not args.json_output:
    output_cli(ret)
    return

  if args.json_output:
    out = args.json_output
    output_json(sys.stdout if out == '-' else open(out, 'wb'), ret)
