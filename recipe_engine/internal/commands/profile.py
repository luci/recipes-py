# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Profile a recipe with cProfile.

Profiles a single recipe+test case combination; steps will behave the same way
they do under test simulation for the given test case.

By default, this will profile the test in question with cProfile and dump the
outcome to stdout.

However, you can also configure it to do a couple additional things:
  - `--sort` takes in a valid cProfile field name and sorts the outcome by that.
  - `--file` takes in a file location to write the profiler result to, for use
      with flameprof or other tools.
'''

import bdb
import cProfile
import sys
import traceback

from ... import config_types
from ... import engine_types

from .. import recipe_deps
from .. import global_shutdown

from ..test.execute_test_case import execute_test_case
from .test.fail_tracker import FailTracker
from .test import test_name



def _safely_gen_tests(recipe):
  # This little function just makes the command exit cleanly if the user aborts
  # the profiler during the GenTests execution.
  print(f'Parsing recipe {recipe.name!r}')
  try:
    yield from recipe.gen_tests()
  except bdb.BdbQuit:
    sys.exit(0)


def _dump_recipes(
    rdeps: recipe_deps.RecipeDeps,
    errmsg: str,
    contain: str=''):
  print(errmsg)
  available = sorted(rdeps.main_repo.recipes)
  msg = 'Available recipes are:'
  if contain:
    if matching := [name for name in available if contain in name]:
      available = matching
      msg = f'Available recipes (containing {contain!r}) are:'

  print(msg)
  for recipe in available:
    print('  ', recipe)


def _parse_profile_target(
    rdeps: recipe_deps.RecipeDeps,
    profile_target: str | None):
  """Parses the singular `profile_target` argument, and returns the Recipe and
  TestData it indicates.

  Prints an error message and returns (None, None) if it fails to parse.
  """
  recipe_name, test_case_name = None, None

  if not profile_target:
    # Try to pull it from previous failures.
    tracker = FailTracker(rdeps.previous_test_failures_path)
    for fail in tracker.recent_fails:
      recipe_name, test_case_name = test_name.split(fail)
      print(
          f'Attempting to pick most recent test failure: {recipe_name}.{test_case_name}.'
      )
      break
  else:
    # They told us something; Could be a recipe or recipe+test
    recipe_name, test_case_name = profile_target, None
    if '.' in recipe_name:
      recipe_name, test_case_name = test_name.split(recipe_name)

  # By this point we need at least the recipe name.
  if recipe_name is None:
    _dump_recipes(
        rdeps,
        'No recipe specified and no recent test failures found.')
    return None, None

  # And the recipe should actually exist in our repo.
  recipe = rdeps.main_repo.recipes.get(recipe_name, None)
  if recipe is None:
    _dump_recipes(rdeps,
                  f'Unable to find recipe {recipe_name!r}.',
                  recipe_name)
    return None, None

  # Now make sure that we have a test case (either specified, or just pick the
  # first one if the user didn't tell us).
  test_data = None
  names = []
  for test_data in _safely_gen_tests(recipe):
    if test_case_name is None or test_data.name == test_case_name:
      return recipe, test_data
    names.append(test_data.name)

  print(
      f'Unable to find test case {test_case_name!r} in recipe {recipe.name!r}'
  )
  print('For reference, we found the following test cases:')
  for name in names:
    print('  ', name)

  return None, None


def add_arguments(parser):
  """Implements the subcommand protocol for recipe engine."""

  parser.add_argument(
      'profile_target',
      nargs='?',
      metavar='recipe_name[.test_case_name]',
      help=('The recipe/module to profile, plus an optional test case name. '
            'If test_case_name is omitted, this will use the first test case. '
            'If omitted entirely, will profile the most recent test failure.'))

  parser.add_argument(
      '--filter', dest='test_filter', action='append', default=test_name.Filter(),
      help=(
        'Profile all tests which match this filter. Mutually exclusive with `profile_target`.'
      ))

  parser.add_argument(
    '--sort', dest='sort', default=-1,
    help=(
      'Field to use to sort the profiler output.'
    ))

  parser.add_argument(
    '--file', dest='file',
    help=(
      'File to write profiler dump to. If not provided, dumps to stdout.'
    ))

  def _main(args):
    if args.test_filter and args.profile_target:
      parser.error("cannot specify profile_target with --filter")

    if args.test_filter:
      for recipe in args.recipe_deps.main_repo.recipes.values():
        if args.test_filter.recipe_name(recipe.name):
          for test_data in _safely_gen_tests(recipe):
            if args.test_filter.full_name(f"{recipe.name}.{test_data.name}"):
              if not _profile_recipe(args.recipe_deps, recipe, test_data, args.sort, args.file):
                return
      return

    recipe, test_data = _parse_profile_target(args.recipe_deps, args.profile_target)
    if recipe is None:
      return

    _profile_recipe(args.recipe_deps, recipe, test_data, args.sort, args.file)

  parser.set_defaults(func=_main)


def _profile_recipe(rdeps: recipe_deps.RecipeDeps, recipe: recipe_deps.Recipe,
                  test_data, sort: str, file: str):
  """Profiles the given recipe + test case."""
  # Reset global state.
  config_types.ResetGlobalVariableAssignments()
  engine_types.PerGreentletStateRegistry.clear()
  global_shutdown.GLOBAL_SHUTDOWN.clear()

  try:
    print(f'RunSteps() # Loaded test case: {recipe.name}.{test_data.name}')
    with cProfile.Profile() as pr:
      execute_test_case(rdeps, recipe.name, test_data)
      if file:
        pr.dump_stats(file)
      else:
        pr.print_stats(sort=sort)
    return True
  except bdb.BdbQuit:
    return False
  except Exception:  # pylint: disable=broad-except
    traceback.print_exc()
