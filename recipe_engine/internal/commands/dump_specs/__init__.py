# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Print information about the current repo's dependencies.

Prints JSON conforming to the schema of the recipes_cfg.DepRepoSpecs
protobuf.
"""

from __future__ import annotations

import argparse


def add_arguments(parser: argparse.ArgumentParser) -> None:

  def _launch(args: argparse.Namespace) -> int:
    from . import cmd
    return cmd.main(args)

  parser.set_defaults(func=_launch)
