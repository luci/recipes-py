#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides simulator test coverage for individual recipes."""

import os

# Importing for side effects on sys.path? Yes... yes we are :(
import test_env  # pylint: disable=W0611,W0403

from common import annotator
from slave import annotated_run
from slave import recipe_config_types
from slave import recipe_loader
from slave import recipe_util

import expect_tests  # pylint: disable=W0403


def RunRecipe(test_data):
  stream = annotator.StructuredAnnotationStream(stream=open(os.devnull, 'w'))
  recipe_config_types.ResetTostringFns()
  # TODO(iannucci): Only pass test_data once.
  result = annotated_run.run_steps(stream, test_data.properties,
                                   test_data.properties, test_data)
  return expect_tests.Result([s.step for s in result.steps_ran.itervalues()])


def GenerateTests():
  mods = recipe_loader.load_recipe_modules(recipe_loader.MODULE_DIRS())

  for recipe_path, recipe_name in recipe_loader.loop_over_recipes():
    recipe = recipe_loader.load_recipe(recipe_name)
    test_api = recipe_loader.create_test_api(recipe.DEPS)
    for test_data in recipe.GenTests(test_api):
      root, name = os.path.split(recipe_path)
      name = os.path.splitext(name)[0]
      expect_path = os.path.join(root, '%s.expected' % name)

      test_data.properties['recipe'] = recipe_name
      yield expect_tests.Test(
          '%s.%s' % (recipe_name, test_data.name),
          RunRecipe, args=(test_data,),
          expect_dir=expect_path,
          expect_base=test_data.name,
          break_funcs=(mods.step.API.__call__, recipe.GenSteps)
      )


if __name__ == '__main__':
  expect_tests.main('recipe_simulation_test', GenerateTests, (
      [os.path.join(x, '*') for x in recipe_util.RECIPE_DIRS()] +
      [os.path.join(x, '*', '*api.py') for x in recipe_util.MODULE_DIRS()]
  ), (
      [os.path.join(x, '*', '*config.py') for x in recipe_util.MODULE_DIRS()]
  ))
