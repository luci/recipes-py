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
  file: file.TEST_API


def RunSteps(api: DEPS):
  try:
    api.file.read_text(
      'does not exist', api.path.start_dir / 'not_there')
    assert False, "never reached"  # pragma: no cover
  except api.file.Error as e:
    assert e.errno_name == 'ENOENT'


def GenTests(api: TEST_DEPS):
  yield (
    api.test('basic')
    + api.step_data('does not exist', api.file.errno('ENOENT'))
  )
