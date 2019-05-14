# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Debug a recipe with the python debugger.

Debugs a single recipe+test case combination; steps will behave the same way
they do under test simulation for the given test case.
'''

import bdb
import pdb
import sys
import traceback

from ..test.execute_test_case import execute_test_case


def add_arguments(parser):
  """Implements the subcommand protocol for recipe engine."""
  parser.add_argument(
      'recipe_name', nargs='?', help='The name of the recipe to debug.')
  parser.add_argument(
      'test_name', nargs='?', help=(
        'The name of the test case in GenTests to debug with. If ommitted '
        'and there is exactly one test case for the recipe, will use that.'
      ))

  def _main(args):
    if not args.recipe_name:
      print 'Available recipes:'
      for recipe in sorted(args.recipe_deps.main_repo.recipes):
        print '  ', recipe
      sys.exit(1)

    recipe = args.recipe_deps.main_repo.recipes[args.recipe_name]
    all_tests = recipe.gen_tests()
    test_data = None
    if len(all_tests) == 1 and not args.test_name:
      test_data = all_tests[0]
    else:
      for test_data in sorted(all_tests, key=lambda t: t.name):
        if test_data.name == args.test_name:
          break
      else:
        print 'Unable to find test case %r in recipe %r' % (
          args.test_name, args.recipe_name)
        print 'For reference, we found the following test cases:'
        for case in all_tests:
          print '  ', case.name
        sys.exit(1)

    _debug_recipe(args.recipe_deps, recipe, test_data)
  parser.set_defaults(func=_main)


def _debug_recipe(recipe_deps, recipe, test_data):
  """Debugs the given recipe + test case.

  Args:

    * recipe_deps (RecipeDeps)
    * recipe (Recipe)
    * test_data (TestData)
  """
  debugger = pdb.Pdb()
  for func in [recipe.global_symbols['RunSteps']]:
    debugger.set_break(
        func.func_code.co_filename,
        func.func_code.co_firstlineno,
        funcname=func.func_code.co_name)

  try:
    def dispatch_thunk(frame, event, arg):
      """Triggers 'continue' command when debugger starts."""
      val = debugger.trace_dispatch(frame, event, arg)
      debugger.set_continue()
      sys.settrace(debugger.trace_dispatch)
      return val
    debugger.reset()
    sys.settrace(dispatch_thunk)
    try:
      execute_test_case(recipe_deps, recipe.name, test_data)
    finally:
      debugger.quitting = 1
      sys.settrace(None)
  except bdb.BdbQuit:
    pass
  except Exception:  # pylint: disable=broad-except
    traceback.print_exc()
    print 'Uncaught exception. Entering post mortem debugging'
    print 'Running \'cont\' or \'step\' will restart the program'
    tback = sys.exc_info()[2]
    debugger.interaction(None, tback)
