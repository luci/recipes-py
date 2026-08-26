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
  filepath = api.path.start_dir / 'some_file'
  size_mb = 300

  MBtoB = lambda x: x * 1024 * 1024
  BtoMB = lambda x: x / (1024 * 1024)

  api.file.truncate('truncate a file', filepath, size_mb)
  filesizes = api.file.filesizes(
      'size of some_file', [filepath], test_data=[MBtoB(size_mb)])
  assert filesizes[0] == MBtoB(size_mb), ("size is %sMB" % BtoMB(filesizes[0]))


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
