# Copyright 2019 The LUCI Authors
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
  dest = api.path.start_dir / 'some_file.json'
  # Test a non-trivial number of keys in a dict.  This tests that the keys
  # are sorted in the output.
  data = {str('key%d' % i): True for i in range(10)}

  api.file.write_json('write_json', dest, data)

  read_data = api.file.read_json('read_json', dest, test_data=data)

  assert read_data == data, (read_data, data)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
  yield api.test(
      'failure',
      api.step_data('read_json',
          api.file.read_json(errno_name='JSON READ FAILURE')),
      status='FAILURE',
  )
