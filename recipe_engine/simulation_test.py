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
  if test_data.whitelist_data:
    whitelist_data  = dict(test_data.whitelist_data)  # copy so we can mutate it
    def filter_expectation(step):
      whitelist = whitelist_data.pop(step['name'], None)
      if whitelist is None:
        return

      whitelist = set(whitelist)  # copy so we can mutate it
      if len(whitelist) > 0:
        whitelist.add('name')
        step = {k: v for k, v in step.iteritems() if k in whitelist}
        whitelist.difference_update(step.keys())
        if whitelist:
          raise ValueError(
            "The whitelist includes fields %r in step %r, but those fields"
            " don't exist."
            % (whitelist, step['name']))
      return step
    raw_expectations = filter(filter_expectation, raw_expectations)

    if whitelist_data:
      raise ValueError(
        "The step names %r were included in the whitelist, but were never run."
        % [s['name'] for s in whitelist_data])

  return expect_tests.Result(raw_expectations)


class SimulationAnnotatorStreamEngine(stream.AnnotatorStreamEngine):

  def __init__(self):
    self._step_buffer_map = {}
    super(SimulationAnnotatorStreamEngine, self).__init__(
        self.step_buffer(None))

  def step_buffer(self, step_name):
    return self._step_buffer_map.setdefault(step_name, StringIO.StringIO())

  def new_step_stream(self, step_config):
    return self._create_step_stream(step_config,
                                    self.step_buffer(step_config.name))


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


class InsufficientTestCoverage(Exception): pass


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

      full_expectation_count = 0
      for test_data in recipe.GenTests(test_api):
        if not test_data.whitelist_data:
          full_expectation_count += 1
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

      if full_expectation_count < 1:
        raise InsufficientTestCoverage(
          'Must have at least 1 test without a whitelist!')
    except:
      info = sys.exc_info()
      new_exec = Exception('While generating results for %r: %s: %s' % (
        recipe_name, info[0].__name__, str(info[1])))
      raise new_exec.__class__, new_exec, info[2]


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
