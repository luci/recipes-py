# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides simulator test coverage for individual recipes."""

import StringIO
import contextlib
import json
import logging
import os
import re
import sys

from . import env
from . import stream
import expect_tests

# This variable must be set in the dynamic scope of the functions in this file.
# We do this instead of passing because the threading system of expect tests
# doesn't know how to serialize it.
_UNIVERSE = None


def RenderExpectation(test_data, raw_expectations):
  """Applies the step filters (e.g. whitelists, etc.) to the raw_expectations,
  if the TestData actually contains any filters.

  Returns the final expect_tests.Result."""
  # map of step_name -> index in raw_expectations
  index = {}
  for i, step in enumerate(raw_expectations):
    index[step['name']] = i

  if test_data.whitelist_data:
    new_result = []
    for step_name, fields in test_data.whitelist_data.iteritems():
      if step_name not in index:
        raise ValueError(
          "The step name %r was included in the whitelist, but was never run."
          % step_name)

      raw_step = raw_expectations[index[step_name]]
      if not fields:
        new_result.append(raw_step)
      else:
        new_step = {'name': raw_step['name']}
        for k in fields:
          if k not in raw_step:
            raise ValueError(
              "The whitelist includes field %r in step %r, but that field"
              " doesn't exist."
              % (k, step_name))
          new_step[k] = raw_step[k]
        new_result.append(new_step)
    raw_expectations = new_result

  return expect_tests.Result(raw_expectations)


class SimulationAnnotatorStreamEngine(stream.AnnotatorStreamEngine):

  def __init__(self):
    self._step_buffer_map = {}
    super(SimulationAnnotatorStreamEngine, self).__init__(
        self.step_buffer(None))

  def step_buffer(self, step_name):
    return self._step_buffer_map.setdefault(step_name, StringIO.StringIO())

  def _new_step_stream(self, step_name, allow_subannotations, nest_level):
    return self._create_step_stream(
        step_name,
        self.step_buffer(step_name),
        allow_subannotations,
        nest_level)


def RunRecipe(test_data):
  """Actually runs the recipe given the GenTests-supplied test_data."""
  from . import config_types
  from . import loader
  from . import run
  from . import step_runner
  from . import stream

  config_types.ResetTostringFns()

  annotator = SimulationAnnotatorStreamEngine()
  stream_engine = stream.ProductStreamEngine(
      stream.StreamEngineInvariants(),
      annotator)
  with stream_engine:
    step_runner = step_runner.SimulationStepRunner(stream_engine, test_data,
                                                   annotator)

    engine = run.RecipeEngine(step_runner, test_data.properties, _UNIVERSE)
    recipe_script = _UNIVERSE.load_recipe(test_data.properties['recipe'])
    api = loader.create_recipe_api(recipe_script.LOADED_DEPS, engine, test_data)
    result = engine.run(recipe_script, api)

    # Don't include tracebacks in expectations because they are too sensitive to
    # change.
    result.result.pop('traceback', None)
    raw_expectations = step_runner.steps_ran + [result.result]

    try:
      return RenderExpectation(test_data, raw_expectations)
    except:
      print
      print "The expectations would have been:"
      json.dump(raw_expectations, sys.stdout, indent=2)
      raise


def test_gen_coverage():
  cover = []

  for path in _UNIVERSE.recipe_dirs:
    cover.append(os.path.join(path, '*'))

  for path in _UNIVERSE.module_dirs:
    cover.append(os.path.join(path, '*', 'example.py'))
    cover.append(os.path.join(path, '*', 'test_api.py'))

  return cover


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
      cover_mods.append(os.path.join(mod_dir_base, '*.py'))

  for recipe_path, recipe_name in _UNIVERSE.loop_over_recipes():
    try:
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
            break_funcs=(recipe.RunSteps,)
        )
    except:
      print 'While generating test cases for %s:%s' % (recipe_path, recipe_name)
      raise


def main(universe, args=None):
  """Runs simulation tests on a given repo of recipes.

  Args:
    universe: a RecipeUniverse object to operate on
    args: command line arguments to expect_tests
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
                    cover_omit=cover_omit(), args=args)
