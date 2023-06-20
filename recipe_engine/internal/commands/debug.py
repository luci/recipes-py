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


def _dump_recipes_and_exit(rdeps, errmsg):
  print(errmsg)
  print('Available recipes are:')
  for recipe in sorted(rdeps.main_repo.recipes):
    print('  ', recipe)
  sys.exit(1)


def add_arguments(parser):
  """Implements the subcommand protocol for recipe engine."""

  parser.add_argument(
      'debug_target',
      nargs='?',
      metavar='recipe_name[.test_case_name]',
      help=('The name of the recipe to debug, plus an optional test case name. '
            'If test_case_name is omitted, this will use the first test case. '
            'If omitted entirely, will debug the most recent test failure.'))

  def _main(args):
    recipe_name, test_case_name = None, None

    if not args.debug_target:
      # Try to pull it from previous failures.
      tracker = FailTracker(args.recipe_deps.previous_test_failures_path)
      for fail in tracker.recent_fails:
        recipe_name, test_case_name = test_name.split(fail)
        print(
            f'Attempting to pick most recent test failure: {recipe_name}.{test_case_name}.'
        )
        break
    else:
      # They told us something; Could be a recipe or recipe+test
      recipe_name, test_case_name = args.debug_target, None
      if '.' in recipe_name:
        recipe_name, test_case_name = test_name.split(recipe_name)

    # By this point we need at least the recipe name.
    if recipe_name is None:
      _dump_recipes_and_exit(
          args.recipe_deps,
          'No recipe specified and no recent test failures found.')

    # And the recipe should actually exist in our repo.
    recipe = args.recipe_deps.main_repo.recipes.get(recipe_name, None)
    if recipe is None:
      _dump_recipes_and_exit(args.recipe_deps,
                             f'Unable to find recipe {recipe_name}.')
    _breakpoint_recipe(recipe)

    # Now make sure that we have a test case (either specified, or just pick the
    # first one if the user didn't tell us).
    test_data = None
    names = []
    for test_data in _safely_gen_tests(recipe):
      if test_case_name is None or test_data.name == test_case_name:
        break
      names.append(test_data.name)
    else:
      print(
          f'Unable to find test case {test_case_name!r} in recipe {recipe.name!r}'
      )
      print('For reference, we found the following test cases:')
      for name in names:
        print('  ', name)
      sys.exit(1)

    _debug_recipe(args.recipe_deps, recipe, test_data)

  parser.set_defaults(func=_main)


def _debug_recipe(rdeps: recipe_deps.RecipeDeps, recipe: recipe_deps.Recipe,
                  test_data):
  """Debugs the given recipe + test case."""
  try:
    print(f'RunSteps() # Loaded test case: {recipe.name}.{test_data.name}')
    execute_test_case(rdeps, recipe.name, test_data)
  except bdb.BdbQuit:
    pass
  except Exception:  # pylint: disable=broad-except
    traceback.print_exc()
    print('Uncaught exception. Entering post mortem debugging')
    print('Running \'cont\' or \'step\' will restart the program')
    debugger.set_pdb_post_mortem()
