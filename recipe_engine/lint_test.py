#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that recipes are on their best behavior.

Checks that recipes only import modules from a whitelist.  Imports are
generally not safe in recipes if they depend on the platform, since
e.g. you can run a recipe simulation for a Windows recipe on Linux.
"""

# TODO(luqui): Implement lint for recipe modules also.

from __future__ import absolute_import
import re
import types


MODULES_WHITELIST = [
  r'base64',
  r'collections',
  r'contextlib',
  r'copy',
  r'datetime',
  r'functools',
  r'hashlib',
  r'itertools',
  r'json',
  r'math',
  r're',
  r'urlparse',
  r'zlib',
]


class ImportViolationError(Exception):
  pass


class TestFailure(Exception):
  pass


def ImportsTest(recipe_path, recipe_name, whitelist, universe_view):
  """Tests that recipe_name only uses allowed imports.

  Returns a list of errors, or an empty list if there are no errors (duh).
  """

  recipe = universe_view.load_recipe(recipe_name)
  for _, val in sorted(recipe.globals.iteritems()):
    if isinstance(val, types.ModuleType):
      module_name = val.__name__
      for pattern in whitelist:
        if pattern.match(val.__name__):
          break
      else:
        yield ('In %s:\n'
               '  Non-whitelisted import of %s' %
               (recipe_path, module_name))


def add_subparser(parser):
  lint_p = parser.add_parser(
      'lint',
      description='Check recipes for stylistic and hygenic issues')
  lint_p.add_argument(
      '--whitelist', '-w', action='append', default=[],
      help='A regexp matching module names to add to the default whitelist. '
           'Use multiple times to add multiple patterns,')

  lint_p.set_defaults(command='lint', func=main)


def main(package_deps, args):
  from . import loader

  universe = loader.RecipeUniverse(package_deps, args.package)
  universe_view = loader.UniverseView(universe, package_deps.root_package)

  whitelist = map(re.compile, MODULES_WHITELIST + args.whitelist)

  errors = []
  for recipe_path, recipe_name in universe_view.loop_over_recipes():
    errors.extend(
        ImportsTest(recipe_path, recipe_name, whitelist, universe_view))

  if errors:
    raise TestFailure('\n'.join(map(str, errors)))
