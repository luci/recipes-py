# Copyright 2026 The LUCI Authors
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
  filepath = api.path.start_dir / 'some_file'
  api.file.write_text('create file', filepath, 'content')

  # Check if it is executable (defaults to True in tests)
  is_exe = api.file.is_executable('check executable', filepath)
  assert is_exe is True

  # Check with false test data
  is_exe_false = api.file.is_executable(
      'check non-executable', filepath, test_data=False)
  assert is_exe_false is False


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
