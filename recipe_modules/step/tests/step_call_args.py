# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import step


@dataclass
class DEPS(RecipeScriptApi):
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  try:
    api.step('bad cmd', 'I\'m a str cmd')
  except ValueError as e:
    assert str(e) == 'cmd must be a list, got "I\'m a str cmd"', e

  try:
    api.step('bad arg', [{}])
  except ValueError as e:
    assert '\'dict\'> is not permitted. cmd is [{}]' in str(e), e

  try:
    api.step('bad cost', None, cost='I\'m a str cost')
  except ValueError as e:
    assert str(e) == (
      'cost must be a None or ResourceCost , got "I\'m a str cost"'), e


def GenTests(api: TEST_DEPS):
  yield (
    api.test('basic') +
    api.post_process(post_process.DropExpectation)
  )
