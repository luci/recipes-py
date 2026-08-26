# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Test to cover legacy aspects of PathTestApi."""

from __future__ import annotations

from recipe_engine import recipe_api
from recipe_engine.post_process import DropExpectation

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import path


@dataclass
class DEPS(RecipeScriptApi):
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  path: path.TEST_API

GETATTR_NAMES = [
    'cache_dir',
    'cleanup_dir',
    'home_dir',
    'start_dir',
    'tmp_base_dir',
]


@recipe_api.ignore_warnings('recipe_engine/CHECKOUT_DIR_DEPRECATED')
def RunSteps(api: DEPS):
  for name in GETATTR_NAMES:
    p = getattr(api.path, name) / 'file'
    assert api.path.exists(p), p

  api.path.checkout_dir = api.path.start_dir / 'somedir'
  assert api.path.exists(getattr(api.path, 'checkout_dir') / 'file')


def GenTests(api: TEST_DEPS):
  paths = [getattr(api.path, name) / 'file' for name in GETATTR_NAMES]
  paths.append(api.path.checkout_dir / 'file')

  yield api.test(
      'basic',
      api.path.exists(*paths),
      api.post_process(DropExpectation),
  )
