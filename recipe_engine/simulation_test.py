# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Provides simulator test coverage for individual recipes."""

import StringIO
import ast
import contextlib
import copy
import json
import logging
import os
import re
import sys
import textwrap
import traceback
import inspect

from collections import OrderedDict, namedtuple

from . import config_types
from . import env
from . import loader
from . import run
from . import step_runner
from . import stream
from expect_tests.util import covers as expect_tests_covers
from expect_tests.main import main as expect_tests_main
from expect_tests.type_definitions import Result, Test, FuncCall
from .checker import Checker, VerifySubset
from google.protobuf import json_format as jsonpb

# These variables must be set in the dynamic scope of the functions in this
# file.  We do this instead of passing because the threading system of expect
# tests doesn't know how to serialize it.
_UNIVERSE_VIEW = None
_ENGINE_FLAGS = None


class PostProcessError(ValueError):
  pass


def _renderExpectation(test_data, step_odict):
  """Applies the step post_process actions to the step_odict, if the
  TestData actually contains any.

  Returns the final expect_tests.Result."""

  failed_checks = []

  for hook, args, kwargs, filename, lineno in test_data.post_process_hooks:
    input_odict = copy.deepcopy(step_odict)
    # we ignore the input_odict so that it never gets printed in full. Usually
    # the check invocation itself will index the input_odict or will use it only
    # for a key membership comparison, which provides enough debugging context.
    checker = Checker(filename, lineno, hook, args, kwargs, input_odict)
    rslt = hook(checker, input_odict, *args, **kwargs)
    failed_checks += checker.failed_checks
    if rslt is not None:
      msg = VerifySubset(rslt, step_odict)
      if msg:
        raise PostProcessError('post_process: steps'+msg)
      # restore 'name'
      for k, v in rslt.iteritems():
        if 'name' not in v:
          v['name'] = k
      step_odict = rslt

  # empty means drop expectation
  result_data = step_odict.values() if step_odict else None
  return Result(result_data, failed_checks)


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


# This maps from (recipe_name,test_name) -> yielded test_data. It's outside of
# RunRecipe so that it can persist between RunRecipe calls in the same process.
_GEN_TEST_CACHE = {}

# allow regex patterns to be 'deep copied' by using them as-is
copy._deepcopy_dispatch[re._pattern_type] = copy._deepcopy_atomic

def RunRecipe(recipe_name, test_name):
  """Actually runs the recipe given the GenTests-supplied test_data."""
  cache_key = (recipe_name, test_name)
  if cache_key not in _GEN_TEST_CACHE:
    recipe_script = _UNIVERSE_VIEW.load_recipe(recipe_name)
    test_api = loader.create_test_api(recipe_script.LOADED_DEPS, _UNIVERSE_VIEW)
    for test_data in recipe_script.gen_tests(test_api):
      _GEN_TEST_CACHE[(recipe_name, test_data.name)] = copy.deepcopy(test_data)

  test_data = _GEN_TEST_CACHE[cache_key]

  config_types.ResetTostringFns()

  annotator = SimulationAnnotatorStreamEngine()
  with stream.StreamEngineInvariants.wrap(annotator) as stream_engine:
    runner = step_runner.SimulationStepRunner(
        stream_engine, test_data, annotator)

    props = test_data.properties.copy()
    props['recipe'] = recipe_name
    engine = run.RecipeEngine(
        runner, props, _UNIVERSE_VIEW, engine_flags=_ENGINE_FLAGS)
    recipe_script = _UNIVERSE_VIEW.load_recipe(recipe_name, engine=engine)

    api = loader.create_recipe_api(
      _UNIVERSE_VIEW.universe.package_deps.root_package,
      recipe_script.LOADED_DEPS,
      recipe_script.path, engine, test_data)
    result = engine.run(recipe_script, api, test_data.properties)

    raw_expectations = runner.steps_ran.copy()
    # Don't include tracebacks in expectations because they are too sensitive to
    # change.
    if _ENGINE_FLAGS.use_result_proto:
      if result.HasField('failure'):
        result.failure.ClearField('traceback')
      result_json = json.loads(
          jsonpb.MessageToJson(result, including_default_value_fields=True))
      result_json['name'] = '$result'

      raw_expectations[result_json['name']] = result_json
    else:
      result.result.pop('traceback', None)
      raw_expectations[result.result['name']] = result.result

    try:
      return _renderExpectation(test_data, raw_expectations)
    except:
      print
      print "The expectations would have been:"
      json.dump(raw_expectations, sys.stdout, indent=2)
      raise


def cover_omit():
  omit = [ ]

  mod_dir_base = _UNIVERSE_VIEW.module_dir
  if os.path.isdir(mod_dir_base):
      omit.append(os.path.join(mod_dir_base, '*', 'resources', '*'))

  # Exclude recipe engine files from simulation test coverage. Simulation tests
  # should cover "user space" recipe code (recipes and modules), not the engine.
  # The engine is covered by unit tests, not simulation tests.
  omit.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '*'))

  return omit


def GenerateTests():
  all_modules = set(_UNIVERSE_VIEW.loop_over_recipe_modules())
  covered_modules = set()

  base_covers = []

  # Make sure disabling strict coverage also disables our additional check
  # for module coverage. Note that coverage will still raise an error if
  # the module is executed by any of the tests, but having less than 100%
  # coverage.
  for module in all_modules:
    mod = _UNIVERSE_VIEW.load_recipe_module(module)
    # Recipe modules can only be covered by tests inside the same module.
    # To make transition possible for existing code (which will require
    # writing tests), a temporary escape hatch is added.
    # TODO(phajdan.jr): remove DISABLE_STRICT_COVERAGE (crbug/693058).
    if (getattr(mod, 'DISABLE_STRICT_COVERAGE', False)):
      covered_modules.add(module)
      base_covers.append(os.path.join(
          _UNIVERSE_VIEW.module_dir, module, '*.py'))

  for recipe_path, recipe_name in _UNIVERSE_VIEW.loop_over_recipes():
    try:
      recipe = _UNIVERSE_VIEW.load_recipe(recipe_name)
      test_api = loader.create_test_api(recipe.LOADED_DEPS, _UNIVERSE_VIEW)

      covers = [recipe_path] + base_covers

      # Example/test recipes in a module always cover that module.
      if ':' in recipe_name:
        module, _ = recipe_name.split(':', 1)
        covered_modules.add(module)
        covers.append(os.path.join(_UNIVERSE_VIEW.module_dir, module, '*.py'))

      for test_data in recipe.gen_tests(test_api):
        root, name = os.path.split(recipe_path)
        name = os.path.splitext(name)[0]
        expect_path = os.path.join(root, '%s.expected' % name)
        yield Test(
            '%s.%s' % (recipe_name, test_data.name),
            FuncCall(RunRecipe, recipe_name, test_data.name),
            expect_dir=expect_path,
            expect_base=test_data.name,
            covers=covers,
            break_funcs=(recipe.run_steps,)
        )
    except:
      info = sys.exc_info()
      new_exec = Exception('While generating results for %r: %s: %s' % (
        recipe_name, info[0].__name__, str(info[1])))
      raise new_exec.__class__, new_exec, info[2]

  uncovered_modules = all_modules.difference(covered_modules)
  if uncovered_modules:
    raise Exception('The following modules lack test coverage: %s' % (
        ','.join(sorted(uncovered_modules))))


def main(universe_view, args=None, engine_flags=None):
  """Runs simulation tests on a given repo of recipes.

  Args:
    universe_view: an UniverseView object to operate on
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

  global _UNIVERSE_VIEW
  _UNIVERSE_VIEW = universe_view
  global _ENGINE_FLAGS
  _ENGINE_FLAGS = engine_flags

  expect_tests_main('recipe_simulation_test', GenerateTests,
                    cover_omit=cover_omit(), args=args)
