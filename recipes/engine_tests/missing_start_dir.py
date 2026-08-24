# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that deleting the current working directory doesn't immediately fail"""

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    path,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  path: path.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  api.step('innocent step', ['bash', '-c', "echo some step"])
  api.step('nuke it', ['rm', '-rf', api.path.start_dir])

  try:
    api.step('bash needs cwd', ['bash', '-c', "echo fail"])
    assert True
  except api.step.StepFailure:  # pragma: no cover
    assert False

  api.step('python does not', ['python3', '-c', 'print("hi")'])


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
