# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import argparse
import os
import sys


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--verify-enum34', action='store_true')
  parser.add_argument('--verify-six', action='store_true')
  opts = parser.parse_args()

  if opts.verify_enum34:
    import enum
    assert enum.version == (1, 1, 6)
  if opts.verify_six:
    import six
    assert six.__version__ == '1.10.0'

  try:
    # ensure that the recipe_engine .vpython env doesn't leak through
    import requests  # pylint: disable=unused-variable
    assert False, "recipe engine .vpython env leaked through!"
  except ImportError:
    pass

  return 0


if __name__ == '__main__':
  sys.exit(main())


##
# Inline VirtualEnv "vpython" spec.
#
# Pick a test package with no dependencies from ".vpython" that
# differs from the package in "test.vpython" file.
#
# This is used in "examples/full.py" along with the "--verify-enum34" flag.
##
# [VPYTHON:BEGIN]
#
# wheel: <
#   name: "infra/python/wheels/enum34-py2"
#   version: "version:1.1.6"
# >
#
# [VPYTHON:END]
##
