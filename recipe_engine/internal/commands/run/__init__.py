# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Run a recipe locally.'''

# TODO(iannucci): add a real docstring

import argparse
import json
import os
import sys

# Give this a high priority so it shows first in help.
__cmd_priority__ = 0

def add_arguments(parser):
  def _properties_file_type(filename):
    with (sys.stdin if filename == '-' else open(filename)) as fil:
      obj = json.load(fil)
      if not isinstance(obj, dict):
        raise argparse.ArgumentTypeError(
          'must contain a JSON object, i.e. `{}`.')
      return obj

  def _parse_prop(prop):
    key, val = prop.split('=', 1)
    try:
      val = json.loads(val)
    except (ValueError, SyntaxError):
      pass  # If a value couldn't be evaluated, keep the string version
    return {key: val}

  def _properties_type(value):
    obj = json.loads(value)
    if not isinstance(obj, dict):
      raise argparse.ArgumentTypeError('must contain a JSON object, i.e. `{}`.')
    return obj

  parser.add_argument(
    '--workdir',
    type=os.path.abspath,
    help='The working directory of recipe execution')
  parser.add_argument(
    '--output-result-json',
    type=os.path.abspath,
    help=(
      'The file to write the JSON serialized returned value '
      ' of the recipe to'))
  prop_group = parser.add_mutually_exclusive_group()
  prop_group.add_argument(
    '--properties-file',
    dest='properties',
    type=_properties_file_type,
    help=(
      'A file containing a json blob of properties. '
      'Pass "-" to read from stdin'))
  prop_group.add_argument(
    '--properties',
    type=_properties_type,
    help='A json string containing the properties')

  parser.add_argument(
    'recipe',
    help='The recipe to execute')
  parser.add_argument(
    'props',
    nargs=argparse.REMAINDER,
    type=_parse_prop,
    help=(
      'A list of property pairs; e.g. shards=5 gn_args=["json", "decoded"] '
      'prefix="foobar", but if this decoding fails the value will be '
      'interpreted as a string, e.g. prop=implicit_string.'))

  def _launch(args):
    from .cmd import main
    return main(args)
  parser.set_defaults(properties={}, func=_launch)
