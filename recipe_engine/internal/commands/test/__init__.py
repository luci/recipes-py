# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Generate or check expectations by simulation.'''

# TODO(iannucci): Add a real docstring.

import argparse
import multiprocessing


# Give this a high priority so it shows second in help.
__cmd_priority__ = 1


def add_arguments(parser):
  def _normalize_filter(filt):
    if not filt:
      raise argparse.ArgumentTypeError('empty filters not allowed')
    # filters missing a test_name portion imply that its a recipe prefix and we
    # should run all tests for the matching recipes.
    return filt if '.' in filt else filt+'*.*'

  subp = parser.add_subparsers(dest='subcommand')

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

  glob_helpstr = (
    'glob filter for the tests to run; '
    'can be specified multiple times; '
    'the globs have the form of '
    '`<recipe_name_glob>[.<test_name_glob>]`. If `.<test_name_glob>` '
    'is omitted, it is implied to be `*.*`, i.e. any recipe with this '
    'prefix and all tests.')

  helpstr = 'Run the tests.'
  run_p = subp.add_parser('run', help=helpstr, description=helpstr)
  run_p.add_argument(
    '--jobs', metavar='N', type=int,
    default=multiprocessing.cpu_count(),
    help='run N jobs in parallel (default %(default)s)')
  run_p.add_argument(
    '--json', metavar='FILE', type=argparse.FileType('w'),
    help='path to JSON output file')
  run_p.add_argument(
    '--filter', action='append', type=_normalize_filter,
    help=glob_helpstr)

  helpstr = 'Re-train recipe expectations.'
  train_p = subp.add_parser('train', help=helpstr, description=helpstr)
  train_p.add_argument(
    '--jobs', metavar='N', type=int,
    default=multiprocessing.cpu_count(),
    help='run N jobs in parallel (default %(default)s)')
  train_p.add_argument(
    '--json', metavar='FILE', type=argparse.FileType('w'),
    help='path to JSON output file')
  train_p.add_argument(
    '--filter', action='append', type=_normalize_filter,
    help=glob_helpstr)
  train_p.add_argument(
    '--no-docs', action='store_false', default=True, dest='docs',
    help='Disable automatic documentation generation.')

  def _launch(args):
    from .cmd import main
    return main(args)
  parser.set_defaults(func=_launch)
