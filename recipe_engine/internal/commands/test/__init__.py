# -*- coding: utf-8 -*-
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Generate or check expectations by simulation.'''

# TODO(iannucci): Add a real docstring.

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

  subp = parser.add_subparsers(
      dest='subcommand',
      metavar='{run, train, list, diff}'
  )

  glob_helpstr = textwrap.dedent('''
    glob filter for the tests to run (can be specified multiple times);
    globs have the form of `<recipe_name_glob>[.<test_name_glob>]`.
    If `.<test_name_glob>` is omitted, it is implied to be `*.*`, i.e
    . any recipe with this prefix and all tests.
  ''')

  helpstr = 'Run the tests.'
  run_p = subp.add_parser(
      'run', help=helpstr, description=helpstr + '\n',
      formatter_class=argparse.RawDescriptionHelpFormatter)
  run_p.add_argument(
      '--jobs', metavar='N', type=int,
      default=multiprocessing.cpu_count(),
      help='run N jobs in parallel (default %(default)s)')
  run_p.add_argument(
      '--json', metavar='FILE', type=argparse.FileType('w'),
      help='path to JSON output file')
  run_p.add_argument(
      '--filter', dest='test_filters', action='append', type=_normalize_filter,
      help=glob_helpstr)

  helpstr = 'Re-train recipe expectations.'
  train_p = subp.add_parser(
      'train', help=helpstr, description=helpstr + '\n',
      formatter_class=argparse.RawDescriptionHelpFormatter)
  train_p.add_argument(
      '--jobs', metavar='N', type=int,
      default=multiprocessing.cpu_count(),
      help='run N jobs in parallel (default %(default)s)')
  train_p.add_argument(
      '--json', metavar='FILE', type=argparse.FileType('w'),
      help='path to JSON output file')
  train_p.add_argument(
      '--filter', dest='test_filters', action='append', type=_normalize_filter,
      help=glob_helpstr)
  train_p.add_argument(
      '--no-docs', action='store_false', default=True, dest='docs',
      help='Disable automatic documentation generation.')

  helpstr = 'Print all test names.'
  list_p = subp.add_parser(
      'list', help=helpstr, description=helpstr)
  list_p.add_argument(
      '--json', metavar='FILE', type=argparse.FileType('w'),
      help='path to JSON output file')

  helpstr = 'Compare results of two test runs.'
  diff_p = subp.add_parser(
      'diff', help=helpstr, description=helpstr)
  diff_p.add_argument(
      '--baseline', metavar='FILE', type=argparse.FileType('r'),
      required=True,
      help='path to baseline JSON file')
  diff_p.add_argument(
      '--actual', metavar='FILE', type=argparse.FileType('r'),
      required=True,
      help='path to actual JSON file')
  diff_p.add_argument(
      '--json', metavar='FILE', type=argparse.FileType('w'),
      help='path to JSON output file')

  def _launch(args):
    if args.subcommand == 'list':
      return run_list(args.recipe_deps, args.json)

    if args.subcommand == 'diff':
      from .diff import run_diff
      return run_diff(args.baseline, args.actual, args.json)

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
  from .common import TestDescription

  tests = [
    TestDescription.test_case_full_name(recipe.name, tc.name)
    for recipe in recipe_deps.main_repo.recipes.values()
    for tc in recipe.gen_tests()
  ]
  tests.sort()

  if json_file:
    json.dump({'format': 1, 'tests': tests}, json_file)
  else:
    print '\n'.join(tests)

  return 0
