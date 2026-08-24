# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  raw_io: raw_io.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  raw_io: raw_io.TEST_API


def RunSteps(api: DEPS):
  doge = api.step('doge',
      ['doge'], stdout=api.raw_io.output(), stderr=api.raw_io.output())
  assert doge.stdout == b'such stdout'
  assert doge.stderr == b'so stderring'


def GenTests(api: TEST_DEPS):
  yield (
    api.test('basic') +
    api.step_data('doge',
      api.raw_io.stream_output('such stdout', stream='stdout'),
      api.raw_io.stream_output('so stderring', stream='stderr')))
