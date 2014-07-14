#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides simulator test coverage for individual recipes."""

import logging
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

  ret = []
  last_result = None
  for step_result in result.steps_ran.itervalues():
    last_result = step_result
    s = step_result.step
    if not s.get('skip'):
      s.pop('can_fail_build', None)
      s.pop('abort_on_failure', None)
      s.pop('always_run', None)
      s.pop('seed_steps', None)
      ret.append(s)

  if result.status_code != 0:
    reason = last_result.abort_reason
    if not reason:
      for name, step_result in reversed(result.steps_ran.items()):
        retcode = step_result.retcode
        if retcode and step_result.step.get('can_fail_build', True):
          reason = 'Step(%r) failed with return_code %d' % (name, retcode)
          break
    if not reason:
      reason = 'UNKNOWN'
    ret.append({
        'name': '$final_result',
        'status_code': result.status_code,
        'reason': reason
    })

  return expect_tests.Result(ret)


def test_gen_coverage():
  return (
      [os.path.join(x, '*') for x in recipe_util.RECIPE_DIRS()] +
      [os.path.join(x, '*', 'example.py') for x in recipe_util.MODULE_DIRS()] +
      [os.path.join(x, '*', 'test_api.py') for x in recipe_util.MODULE_DIRS()]
  )

@expect_tests.covers(test_gen_coverage)
def GenerateTests():
  cover_mods = []
  for mod_dir_base in recipe_util.MODULE_DIRS():
    if os.path.isdir(mod_dir_base):
      cover_mods.append(os.path.join(mod_dir_base, '*', '*api.py'))

  for recipe_path, recipe_name in recipe_loader.loop_over_recipes():
    recipe = recipe_loader.load_recipe(recipe_name)
    test_api = recipe_loader.create_test_api(recipe.DEPS)

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


if __name__ == '__main__':
  # annotated_run.py has different behavior when these environment variables
  # are set, so unset to make simulation tests environment-invariant.
  for env_var in ['TESTING_MASTER_HOST',
                  'TESTING_MASTER',
                  'TESTING_SLAVENAME']:
    if env_var in os.environ:
      logging.warn("Ignoring %s environment variable." % env_var)
      os.environ.pop(env_var)

  expect_tests.main('recipe_simulation_test', GenerateTests)
