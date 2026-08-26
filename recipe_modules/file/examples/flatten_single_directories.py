# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    file,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  file: file.API
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  base = api.path.start_dir / 'dir'
  long_dir = base / 'which_has' / 'some' / 'singular' / 'subdirs'

  api.file.ensure_directory('make chain of single dirs', long_dir)

  filenames = ['bunch', 'of', 'files']
  for n in filenames:
    api.file.truncate('touch %s' % n, long_dir / n, 1)

  api.file.flatten_single_directories('remove single dirs', base)
  # To satisfy simulation; run this example for real to get the useful
  # assertions below.
  for n in filenames:
    api.path.mock_add_paths(base / n)

  for n in filenames:
    path = base / n
    assert api.path.exists(path), path


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
