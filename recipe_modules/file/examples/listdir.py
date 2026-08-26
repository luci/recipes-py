# Copyright 2017 The LUCI Authors
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
  root_dir = api.path.start_dir / 'root_dir'
  api.file.ensure_directory('ensure root_dir', root_dir)

  listdir_result = api.file.listdir('listdir root_dir', root_dir, test_data=[])
  assert listdir_result == [], (listdir_result, [])

  some_file = root_dir / 'some file'
  sub_dir = root_dir / 'sub'
  in_subdir = sub_dir / 'f'

  api.file.write_text('write some file', some_file, 'some data')
  api.file.ensure_directory('mkdir', sub_dir)
  api.file.write_text('write another file', in_subdir, 'some data')

  result = api.file.listdir('listdir root_dir', root_dir,
                            test_data=['some file', 'sub'])
  expected = [some_file, sub_dir]
  assert result == expected, (result, expected)

  result = api.file.listdir('listdir root_dir', root_dir,
                            recursive=True,
                            test_data=['some file', 'sub/f'])
  expected = [some_file, in_subdir]
  assert result == expected, (result, expected)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
