# Copyright 2022 The LUCI Authors
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
  file: file.TEST_API


def RunSteps(api: DEPS):
  api.file.write_text('Writing text to file.txt', 'file.txt', 'abcd')
  api.file.chmod('Changing file permissions for file.txt', 'file.txt', '777')

  api.file.chmod('Changing file permissions for start dir', api.path.start_dir,
                 '777', recursive=True)

  try:
    api.file.chmod('File does not exist', 'non-existent-file.txt', '777')
  except Exception as e:
    assert isinstance(e, api.file.Error) and e.errno_name == 'ENOENT'


def GenTests(api: TEST_DEPS):
  yield (api.test('basic') +
         api.step_data('File does not exist', api.file.errno('ENOENT')))
