# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Checks recipes for stylistic and hygienic issues.

Currently only checks that recipes only import python modules from an allowlist.

Imports are not safe in recipes if they depend on the platform or have functions
which otherwise directly interact with the OS (since all recipe code must run
correctly for all platforms under simulation).
"""

# TODO(luqui): Implement lint for recipe modules also.

from __future__ import absolute_import, print_function
import argparse
import re
import types

from future.utils import iteritems, itervalues

ALLOWED_MODULES = [
    r'ast',
    r'base64',
    r'collections',
    r'contextlib',
    r'copy',
    r'datetime',
    r'difflib',
    r'fnmatch',
    r'functools',
    r'hashlib',
    r'itertools',
    r'json',
    r'math',
    r're',
    r'string',
    r'textwrap',
    r'urlparse',
    r'zlib',

    # non stdlib
    r'attr',
    r'google\.protobuf',

    # From recipe ecosystem
    r'PB',
    r'RECIPE_MODULES',
]


def ImportsTest(recipe, allowed_modules):
  """Tests that recipe_name only uses allowed imports.

  Returns a list of errors, or an empty list if there are no errors (duh).
  """

  for _, val in sorted(iteritems(recipe.global_symbols)):
    if isinstance(val, types.ModuleType):
      module_name = val.__name__
      for pattern in allowed_modules:
        if pattern.match(module_name):
          break
      else:
        yield ('In %s:\n'
               '  Disallowed import of %s' % (recipe.path, module_name))


def add_arguments(parser):
  # TODO(iannucci): merge this with the test command, doesn't need to be top
  # level.
  parser.add_argument(
      '--allowlist',
      '-a',
      action='append',
      default=[],
      help=('A regexp matching module names to add to the default allowlist. '
            'Use multiple times to add multiple patterns,'))

  parser.add_argument(
      '--whitelist',
      '-w',
      action='append',
      dest='allowlist',
      help=argparse.SUPPRESS)

  parser.set_defaults(func=main, skip_deps=True)


def main(args):
  allowed_modules = tuple(map(re.compile, ALLOWED_MODULES + args.allowlist))

  errors = []
  for recipe in itervalues(args.recipe_deps.main_repo.recipes):
    errors.extend(ImportsTest(recipe, allowed_modules))

  if errors:
    print('\n'.join(str(e) for e in errors))
    return 1
  return 0
