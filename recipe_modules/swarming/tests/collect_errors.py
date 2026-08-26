# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    path,
    swarming,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  path: path.API
  swarming: swarming.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  output_dir = api.path.mkdtemp('swarming')
  text_dir = api.path.mkdtemp('swarming')

  with api.assertions.assertRaises(ValueError):
    # Two Paths in task_output_stdout are not allowed.
    api.swarming.collect('collect', ['1234'],
                         output_dir=output_dir,
                         task_output_stdout=[output_dir, text_dir])


def GenTests(api: TEST_DEPS):
  yield (api.test('basic') + api.post_process(DropExpectation))
