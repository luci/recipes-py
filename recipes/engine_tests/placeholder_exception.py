# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that placeholders can't wreck the world by exhausting the step stack.
"""

from __future__ import annotations

from recipe_engine import post_process
from recipe_engine.util import InputPlaceholder
from recipe_engine.recipe_api import StepFailure

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

class BadPlaceholder(InputPlaceholder):
  def render(self, test):
    raise Exception("EXPLOSION")

  def __repr__(self):
    return '<BadPlaceholder>'


def RunSteps(api: DEPS):
  api.step('innocent step', ['bash', '-c', "echo some step"])

  ph = BadPlaceholder('name')
  ph.namespaces = ('fake', 'namespace')

  api.step('bad step', ['echo', ph])
  raise ValueError('Never reached')   # pragma: no cover


def GenTests(api: TEST_DEPS):
  yield (
    api.test('basic') +
    api.expect_exception('Exception') +
    api.post_process(post_process.StatusException) +
    api.post_process(post_process.SummaryMarkdown,
                     "Uncaught Exception: Exception('EXPLOSION')") +
    api.post_process(post_process.DropExpectation)
  )
