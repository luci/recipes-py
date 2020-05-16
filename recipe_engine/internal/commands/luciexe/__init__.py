# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

'''Implement the "luciexe" protocol.

This expects to read a build.proto[1] Build message on stdin (binary-encoded
protobuf), and will execute the task accordingly, selecting the recipe to run
from the 'recipe' property of the `Build.input.properties` field.

This synthesizes properties from the Build message:
  * $recipe_engine/runtime['is_experimental'] = Build.input.experimental
  * $recipe_engine/runtime['is_luci'] = true
  * $recipe_engine/path['temp_dir'] = os.environ['TMP']
  * $recipe_engine/path['cache_dir'] = os.environ['LUCI_CACHE_DIR']
'''

import argparse
import sys
import logging


LOG = logging.getLogger(__name__)


class RunBuildContractViolation(Exception):
  pass


def add_arguments(parser):
  parser.add_argument(
      '--final-state', type=argparse.FileType('wb'),
      help='Path to write the final build.proto state to (as binary PB).')
  parser.add_argument(
      '--build-proto-jsonpb', action='store_true',
      help=(
        'If specified, output build.proto datagrams as JSONPB instead of PB. '
        'Only for debugging.'
      ))

  def _launch(args):
    from .cmd import main
    try:
      return main(args)
    except RunBuildContractViolation as ex:
      LOG.fatal('"luciexe" protocol contract violation: %s', ex)
      return 1

  def _post(_error, _args):
    logging.basicConfig(level=logging.INFO)

  parser.set_defaults(func=_launch, postprocess_func=_post)
