# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import argparse
import fnmatch
import re
import typing

import attr


# TODO(crbug.com/1057298) Recipes can actually have '.' characters in their name
# and this will fail to get the recipe name. Recipes should be restricted from
# having '.' characters in their name.
def split(test_name):
  """Split a fully-qualified test name.

  Returns:
    A tuple: (recipe name, simple test name)
  """
  recipe, simple_test_name = test_name.split('.', 1)
  return recipe, simple_test_name


@attr.s
class Filter:
  """Filter is an argparse `type` which collects --filter arguments from the
  CLI into a usable filter object.
  """
  # TODO: Also track module names indicated by the filters.
  # TODO: Upstream this into RecipeDeps so that it will only scan the
  # modules/recipes that we're interested in.
  _recipe_patterns : typing.List[str] = attr.ib(default=[])
  _full_test_name_patterns : typing.List[str] = attr.ib(default=[])

  _compiled_recipe_pattern : str = attr.ib(default=None)
  _compiled_test_name_pattern : str = attr.ib(default=None)

  def append(self, filt: str):
    """Argparse calls this function with each argument to --filter on the
    command line."""
    if not filt:
      raise argparse.ArgumentTypeError('empty --filter values are not allowed')

    # filters missing a test_name portion imply that it is a recipe prefix and we
    # should run all tests for any recipes which match.
    filt = filt if '.' in filt else filt+'*.*'

    self._recipe_patterns.append(fnmatch.translate(split(filt)[0]))
    self._full_test_name_patterns.append(fnmatch.translate(filt))

  def __bool__(self):
    """Returns True if this object has any filter patterns."""
    # NOTE: self._recipe_patterns implies that self._full_test_name_patterns
    # also has values.
    return bool(self._recipe_patterns)

  def recipe_name(self, recipe_name: str) -> bool:
    """Returns True if `recipe_name` matches the accumulated filter state.

    Note that a complete absence of --filter arguments will always return True.
    """
    if not self._recipe_patterns:
      return True

    if self._compiled_recipe_pattern is None:
      self._compiled_recipe_pattern = re.compile('|'.join(self._recipe_patterns))

    return self._compiled_recipe_pattern.match(recipe_name)

  def full_name(self, test_name: str) -> bool:
    """Returns True if `test_name` matches the accumulated filter state.

    Note that a complete absence of --filter arguments will always return True.
    """
    if not self._full_test_name_patterns:
      return True

    if self._compiled_test_name_pattern is None:
      self._compiled_test_name_pattern = re.compile('|'.join(self._full_test_name_patterns))

    return self._compiled_test_name_pattern.match(test_name)
