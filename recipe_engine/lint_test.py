#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests that recipes are on their best behavior.

Checks that recipes only import modules from a whitelist.  Imports are
generally not safe in recipes if they depend on the platform, since
e.g. you can run a recipe simulation for a Windows recipe on Linux.
"""

import re
import types

import test_env  # pylint: disable=W0611,W0403

from slave import recipe_loader


MODULES_WHITELIST = map(re.compile, [
  r'datetime',
  r'json',
  r're',

  r'slave\.recipe_api',

  # Skia does some evil ... :/
  r'common\.skia\..*',
  r'slave\.skia\..*',
])


class ImportViolationError(Exception):
  pass


class TestFailure(Exception):
  pass


def ImportsTest(recipe_path, recipe_name, universe):
  """Tests that recipe_name only uses allowed imports.

  Returns a list of errors, or an empty list if there are no errors (duh).
  """

  recipe = universe.load_recipe(recipe_name)
  for attr in dir(recipe):
    val = getattr(recipe, attr)
    if isinstance(val, types.ModuleType):
      module_name = val.__name__
      for pattern in MODULES_WHITELIST:
        if pattern.match(val.__name__):
          break
      else:
        yield ('In %s:\n'
               '  Non-whitelisted import of %s' %
               (recipe_path, module_name))


def MainTest():
  universe = recipe_loader.RecipeUniverse()

  errors = []
  for recipe_path, recipe_name in recipe_loader.loop_over_recipes():
    errors.extend(ImportsTest(recipe_path, recipe_name, universe))

  if errors:
    raise TestFailure('\n'.join(map(str, errors)))


if __name__ == '__main__':
  MainTest()
