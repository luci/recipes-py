# Copyright 2014-2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides simulator test coverage for individual recipes."""

import logging
import re
import os
import sys

from . import expect_tests

# This variable must be set in the dynamic scope of the functions in this file.
# We do this instead of passing because the threading system of expect tests
# doesn't know how to serialize it.
_UNIVERSE = None

def RunRecipe(test_data):
  from .third_party import annotator
  from . import main
  from . import config_types

  stream = annotator.StructuredAnnotationStream(stream=open(os.devnull, 'w'))
  config_types.ResetTostringFns()
  result = main.run_steps(
      test_data.properties, stream, _UNIVERSE, test_data)

  return expect_tests.Result(list(result.steps_ran.values()))


def test_gen_coverage():
  return (
      [os.path.join(x, '*') for x in _UNIVERSE.recipe_dirs] +
      [os.path.join(x, '*', 'example.py') for x in _UNIVERSE.module_dirs] +
      [os.path.join(x, '*', 'test_api.py') for x in _UNIVERSE.module_dirs]
  )

def cover_omit():
  omit = [ ]
  for mod_dir_base in _UNIVERSE.module_dirs:
    if os.path.isdir(mod_dir_base):
      omit.append(os.path.join(mod_dir_base, '*', 'resources', '*'))
  return omit

@expect_tests.covers(test_gen_coverage)
def GenerateTests():
  from . import loader

  cover_mods = [ ]
  for mod_dir_base in _UNIVERSE.module_dirs:
    if os.path.isdir(mod_dir_base):
      cover_mods.append(os.path.join(mod_dir_base, '*', '*.py'))

  for recipe_path, recipe_name in _UNIVERSE.loop_over_recipes():
    recipe = _UNIVERSE.load_recipe(recipe_name)
    test_api = loader.create_test_api(recipe.LOADED_DEPS, _UNIVERSE)

    covers = cover_mods + [recipe_path]

    for test_data in recipe.GenTests(test_api):
      root, name = os.path.split(recipe_path)
      name = os.path.splitext(name)[0]
      expect_path = os.path.join(root, '%s.expected' % name)

      test_data.properties['recipe'] = recipe_name.replace('\\', '/')
      yield expect_tests.Test(
          '%s.%s' % (recipe_name, test_data.name),
          expect_tests.FuncCall(RunRecipe, test_data),
          expect_dir=expect_path,
          expect_base=test_data.name,
          covers=covers,
          break_funcs=(recipe.GenSteps,)
      )


def main(universe):
  """Runs simulation tests on a given repo of recipes.

  Args:
    universe: a RecipeUniverse to operate on.
  Returns:
    Doesn't -- exits with a status code
  """

  # annotated_run has different behavior when these environment variables
  # are set, so unset to make simulation tests environment-invariant.
  for env_var in ['TESTING_MASTER_HOST',
                  'TESTING_MASTER',
                  'TESTING_SLAVENAME']:
    if env_var in os.environ:
      logging.warn("Ignoring %s environment variable." % env_var)
      os.environ.pop(env_var)

  global _UNIVERSE
  _UNIVERSE = universe
  expect_tests.main('recipe_simulation_test', GenerateTests,
                    cover_omit=cover_omit())
