# Copyright 2021 The LUCI Authors
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
  some_dir = api.path.start_dir / 'some_dir'
  api.file.ensure_directory('ensure some_dir', some_dir)

  some_file = some_dir / 'some file'

  api.file.write_text('write some file', some_file, 'some data')

  result = api.file.file_hash(some_file,
                              test_data='deadbeef')
  expected = 'deadbeef'
  api.assertions.assertEqual(result, expected)

  another_file = api.path.start_dir / 'another_file'
  api.file.write_text('write another file', another_file, 'some data')

  result = api.file.file_hash(another_file,
                              test_data='beefdead')
  expected = 'beefdead'
  api.assertions.assertEqual(result, expected)

  result = api.file.file_hash(another_file)
  expected = '02f88ac238b7aef5df694b0a14957d5a8da6ea88f4cc12ffa5ed56ad98dcc2ed'
  api.assertions.assertEqual(result, expected)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
