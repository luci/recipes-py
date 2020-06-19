# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Print information about the current repo's dependencies.

Prints JSON conforming to the schema of the recipes_cfg.DepRepoSpecs
protobuf.
"""


def add_arguments(parser):

  def _launch(args):
    from .cmd import main
    return main(args)

  parser.set_defaults(func=_launch)
