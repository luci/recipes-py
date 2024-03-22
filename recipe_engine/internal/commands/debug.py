# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Debug a recipe with a python debugger.

Debugs a single recipe+test case combination; steps will behave the same way
they do under test simulation for the given test case.

By default, this will open a `pdb` debugger with two breakpoints set:
  1) At the very top of the selected recipe (i.e. first statement in the file).
  2) At the very top of the RunSteps function of the selected recipe.

However, you can also use VSCode and PyCharm's remote debugging facilities (or
other editors which are compatible with these remote debugging protocols).

See `doc/user_guide.md` for more information on how to set these up.
'''

import ast
import bdb
import sys
import traceback
import typing

from ... import config_types
from ... import engine_types

from .. import debugger
from .. import recipe_deps
from .. import global_shutdown

from ..test.execute_test_case import execute_test_case
from .test.fail_tracker import FailTracker
from .test import test_name


_recipes_breakpointed = set()

def _breakpoint_recipe(recipe):
  if debugger.should_set_implicit_breakpoints():
    if recipe.name not in _recipes_breakpointed:
      with open(recipe.path, 'rb') as recipe_file:
        parsed = ast.parse(recipe_file.read(), recipe.path)
        debugger.set_implicit_pdb_breakpoint(recipe.path, parsed.body[0].lineno)

      func = recipe.global_symbols['RunSteps']
      debugger.set_implicit_pdb_breakpoint(
          func.__code__.co_filename,
          func.__code__.co_firstlineno,
          funcname=func.__code__.co_name)

      _recipes_breakpointed.add(recipe.name)


def _safely_gen_tests(recipe):
  # This little function just makes the command exit cleanly if the user aborts
  # the debugger during the GenTests execution.
  print(f'Parsing recipe {recipe.name!r}')
  try:
    yield from recipe.gen_tests()
  except bdb.BdbQuit:
    sys.exit(0)


def _dump_recipes(rdeps, errmsg, contain=''):
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


def _parse_debug_target(
    rdeps: recipe_deps.RecipeDeps,
    debug_target: typing.Optional[str]):
  """Parses the singular `debug_target` argument, and returns the Recipe and
  TestData it indicates.

  Prints an error message an returns (None, None) if it fails to parse.
  """
  recipe_name, test_case_name = None, None

  if not debug_target:
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
    recipe_name, test_case_name = debug_target, None
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
  _breakpoint_recipe(recipe)

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
      'debug_target',
      nargs='?',
      metavar='recipe_name[.test_case_name]',
      help=('The name of the recipe to debug, plus an optional test case name. '
            'If test_case_name is omitted, this will use the first test case. '
            'If omitted entirely, will debug the most recent test failure.'))

  parser.add_argument(
      '--filter', dest='test_filter', action='append', default=test_name.Filter(),
      help=(
        'Debug all tests which match this filter. Mutually exclusive with `debug_target`.'
      ))

  def _main(args):
    if args.test_filter and args.debug_target:
      parser.error("cannot specify debug_target with --filter")

    if args.test_filter:
      for recipe in args.recipe_deps.main_repo.recipes.values():
        if args.test_filter.recipe_name(recipe.name):
          _breakpoint_recipe(recipe)
          for test_data in _safely_gen_tests(recipe):
            if args.test_filter.full_name(f"{recipe.name}.{test_data.name}"):
              if not _debug_recipe(args.recipe_deps, recipe, test_data):
                return
      return

    recipe, test_data = _parse_debug_target(args.recipe_deps, args.debug_target)
    if recipe is None:
      return

    _debug_recipe(args.recipe_deps, recipe, test_data)

  parser.set_defaults(func=_main)


def _debug_recipe(rdeps: recipe_deps.RecipeDeps, recipe: recipe_deps.Recipe,
                  test_data):
  """Debugs the given recipe + test case."""
  # Reset global state.
  config_types.ResetGlobalVariableAssignments()
  engine_types.PerGreentletStateRegistry.clear()
  global_shutdown.GLOBAL_SHUTDOWN.clear()

  try:
    print(f'RunSteps() # Loaded test case: {recipe.name}.{test_data.name}')
    execute_test_case(rdeps, recipe.name, test_data)
    return True
  except bdb.BdbQuit:
    return False
  except Exception:  # pylint: disable=broad-except
    traceback.print_exc()
    print('Uncaught exception. Entering post mortem debugging')
    print('Running \'cont\' or \'step\' will restart the program')
    debugger.set_pdb_post_mortem()
