# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Calculates the affected recipes and/or modules from a set of modified files.

Useful for triggering additional testing based on e.g. patches to the recipes.

This takes in analyze.proto's Input message as JSONPB, and returns an Output
message in JSONPB.
"""

import sys
import argparse


def add_arguments(parser):
  parser.add_argument(
    'input', type=argparse.FileType('r'),
    help='Path to a JSON object. Valid fields: "files", "recipes". See'
         ' analyze.proto file for more information')
  parser.add_argument(
    'output', type=argparse.FileType('w'), default=sys.stdout,
    help='The file to write output to. See analyze.proto for more information.')

  def _launch(args):
    from .cmd import main
    return main(args)
  parser.set_defaults(func=_launch, skip_dev=True)
