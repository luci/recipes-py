# -*- coding: utf-8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Generate or check expectations by simulation.'''

# TODO(iannucci): Add a real docstring.

from __future__ import print_function

import argparse
import json
import multiprocessing
import textwrap


# Give this a high priority so it shows second in help.
__cmd_priority__ = 1


def add_arguments(parser):
  def _normalize_filter(filt):
    if not filt:
      raise argparse.ArgumentTypeError('empty filters not allowed')
    # filters missing a test_name portion imply that its a recipe prefix and we
    # should run all tests for the matching recipes.
    return filt if '.' in filt else filt+'*.*'

  subp = parser.add_subparsers(dest='subcommand', metavar='{run, train, list}')

  status_info = textwrap.dedent('''
    Key for non-verbose symbols (no-emoji equivalent in parens):

      .  (.) - The test passed. This uses a '.' even in emoji mode to make the
               other outcomes stand out without as much visual fatigue.
      ⚡ (D) - Test produced an expectation diff. Review diff to see if this was
               intentional or not.
      🔥 (E) - The recipe crashed (raised uncaught exception) in a way that the
               test specification wasn't expecting.
      ❌ (X) - `post_process` assertions failed.
      🛑 (S) - Test case specification was bad/invalid.
      🌟 (R) - (train mode) The test expectation was deleted from disk.
      💾 (D) - (train mode) The test expectation was updated on disk.
      🆘 (!) - Internal test harness error (file a Infra>Platform>Recipes bug)
  ''')

  glob_helpstr = textwrap.dedent('''
    glob filter for the tests to run (can be specified multiple times);
    globs have the form of `<recipe_name_glob>[.<test_name_glob>]`.
    If `.<test_name_glob>` is omitted, it is implied to be `*.*`, i.e
    . any recipe with this prefix and all tests.
  ''')

  helpstr = 'Run the tests.'
  run_p = subp.add_parser(
      'run', help=helpstr, description=helpstr + '\n' + status_info,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  run_p.add_argument(
      '--jobs', metavar='N', type=int,
      default=multiprocessing.cpu_count(),
      help='run N jobs in parallel (default %(default)s)')
  run_p.add_argument(
      '--filter', dest='test_filters', action='append', type=_normalize_filter,
      help=glob_helpstr)
  run_p.add_argument(
      '--json', type=argparse.FileType('w'), help=argparse.SUPPRESS)
  run_p.add_argument(
      '--full-stacks', dest='filtered_stacks', default=True,
      action='store_false', help=(
        'By default, tests display filtered stacks for better readability. '
        'Setting this flag will turn this filtering off.'
      ))
  run_p.add_argument(
      '--no-emoji', dest='use_emoji', action='store_false', default=True,
      help='Use text symbols instead of emoji.')
  run_p.add_argument(
      '--stop',
      '-x',
      action='store_true',
      help=('Stop running tests after first error or failure.'))
  run_p.add_argument(
      '--no-docs',
      action='store_false', default=True, dest='docs',
      help='Disable the check for readme file change(WIP).')

  helpstr = 'Re-train recipe expectations.'
  train_p = subp.add_parser(
      'train', help=helpstr, description=helpstr + '\n' + status_info,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  train_p.add_argument(
      '--jobs', metavar='N', type=int,
      default=multiprocessing.cpu_count(),
      help='run N jobs in parallel (default %(default)s)')
  train_p.add_argument(
      '--filter', dest='test_filters', action='append', type=_normalize_filter,
      help=glob_helpstr)
  train_p.add_argument(
      '--no-docs', action='store_false', default=True, dest='docs',
      help='Disable automatic documentation generation.')
  train_p.add_argument(
      '--json', type=argparse.FileType('w'), help=argparse.SUPPRESS)
  train_p.add_argument(
      '--full-stacks', dest='filtered_stacks', default=True,
      action='store_false', help=(
        'By default, tests display filtered stacks for better readability. '
        'Setting this flag will turn this filtering off.'
      ))
  train_p.add_argument(
      '--no-emoji', dest='use_emoji', action='store_false', default=True,
      help='Use text symbols instead of emoji.')
  train_p.add_argument(
      '--stop',
      '-x',
      action='store_true',
      help=('Stop running tests after first error or failure.'))

  helpstr = 'Print all test names.'
  list_p = subp.add_parser(
      'list', help=helpstr, description=helpstr)
  list_p.add_argument(
      '--json', metavar='FILE', type=argparse.FileType('w'),
      help='path to JSON output file')

  # The _runner subcommand is hidden from users, but is used in subprocesses
  # to actually run tests.
  runner_p = subp.add_parser('_runner')
  runner_p.add_argument('--cov-file')
  runner_p.add_argument('--full-stacks', dest='filtered_stacks', default=True,
                        action='store_false')
  runner_p.add_argument('--train', action='store_true', default=False)
  runner_p.add_argument('--cover-module-imports', action='store_true',
                        default=False)

  def _launch(args):
    if args.subcommand == 'list':
      return run_list(args.recipe_deps, args.json)

    if args.subcommand == '_runner':
      from .runner import main
      try:
        return main(args.recipe_deps, args.cov_file, args.filtered_stacks,
                    args.train, args.cover_module_imports)
      except KeyboardInterrupt:
        return 0

    from .run_train import main
    return main(args)
  parser.set_defaults(func=_launch)


def run_list(recipe_deps, json_file):
  """Runs the `test list` subcommand.

  Lists all tests either to stdout or to a JSON file.

  Args:

    * recipe_deps (RecipeDeps)
    * json_file (writable file obj|None) - If non-None, has a JSON file written
      to it in the form of `{"format": 1, "tests": ["test", "names"]}`

  Returns 0
  """
  tests = [
    '%s.%s' % (recipe.name, tc.name)
    for recipe in recipe_deps.main_repo.recipes.values()
    for tc in recipe.gen_tests()
  ]
  tests.sort()

  if json_file:
    json.dump({'format': 1, 'tests': tests}, json_file)
  else:
    print('\n'.join(tests))

  return 0
