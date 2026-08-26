# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    file,
    json,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  file: file.API
  json: json.API
  path: path.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  dest = api.path.start_dir / 'some file'
  data = b'\xef\xbb\xbft'

  api.file.write_raw('write a file', dest, data)
  api.file.copy('copy it', dest, api.path.start_dir / 'new path')
  read_data = api.file.read_raw(
    'read it', api.path.start_dir / 'new path', test_data=data)

  assert read_data == data, (read_data, data)

  api.file.move('move it', api.path.start_dir / 'new path',
                api.path.start_dir / 'new new path')

  read_data = api.file.read_raw(
    'read it', api.path.start_dir / 'new new path', test_data=data)

  assert read_data == data, (read_data, data)


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
