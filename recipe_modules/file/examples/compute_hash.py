# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    file,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  file: file.API
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  base_path = api.path.start_dir
  some_dir = api.path.start_dir / 'some_dir'
  api.file.ensure_directory('ensure some_dir', some_dir)

  some_file = some_dir / 'some file'
  sub_dir = some_dir / 'sub'
  in_subdir = sub_dir / 'f'

  api.file.write_text('write some file', some_file, 'some data')
  api.file.ensure_directory('ensure sub_dir', sub_dir)
  api.file.write_text('write another file', in_subdir, 'some data')

  result = api.file.compute_hash('compute_hash some_dir', [some_dir],
                                 base_path, test_data='deadbeef')
  expected = 'deadbeef'
  api.assertions.assertEqual(result, expected)

  some_other_dir = api.path.start_dir / 'some_other_dir'
  api.file.ensure_directory('ensure some_other_dir', some_other_dir)

  some_other_file = some_other_dir / 'new_f'
  api.file.write_text('write new_f file', some_other_file, 'some data')

  result = api.file.compute_hash('compute_hash of list of dir',
                                 [some_dir, some_other_dir],
                                 base_path,
                                 test_data='abcdefab')
  expected = 'abcdefab'
  api.assertions.assertEqual(result, expected)

  another_file = api.path.start_dir / 'another_file'
  api.file.write_text('write another file', another_file, 'some data')

  result = api.file.compute_hash('compute_hash of list of dirs and file',
                                 [some_dir, some_other_dir, another_file],
                                 base_path, test_data='beefdead')
  expected = 'beefdead'
  api.assertions.assertEqual(result, expected)

  result = api.file.compute_hash('compute_hash of without testdata',
                                 [some_dir, some_other_dir, another_file],
                                 base_path)
  expected = '04ee6be3875f1c09bb34759a1ce7315d67b017716505ebff7df5a290b7ee3b20'
  api.assertions.assertEqual(result, expected)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
