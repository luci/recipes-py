# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Roll dependencies of a recipe repo forward."""

# TODO(iannucci): Add a real docstring.

import argparse


def add_arguments(parser):
  parser.add_argument(
      '--output-json',
      type=argparse.FileType('w', encoding='utf-8'),
      help='A json file to output information about the roll to.')
  parser.add_argument(
      '--verbose-json',
      action='store_true',
      help=(
        'Emit even more data in the output-json file. Requires --output-json.'
      ))

  def _launch(args):
    from .cmd import main
    return main(args)
  def _postprocess_func(error, args):
    if args.verbose_json and not args.output_json:
      error('--verbose-json passed without --output-json')

  parser.set_defaults(
      func=_launch, postprocess_func=_postprocess_func)
