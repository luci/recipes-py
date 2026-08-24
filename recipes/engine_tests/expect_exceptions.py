# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that tests with multiple exceptions are handled correctly."""

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi


@dataclass
class DEPS(RecipeScriptApi):
  pass


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass

def my_function(): # pragma: no cover
  exceptions = []
  for exc_type in (ValueError, TypeError):
    try:
      raise exc_type('BAD DOGE')
    except Exception as exc:
      exceptions.append(exc)

  if exceptions:
    raise ExceptionGroup('multiple exceptions', exceptions)


def RunSteps(api: DEPS):
  my_function()


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.expect_exception('TypeError'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: ExceptionGroup('multiple exceptions', "
          "[ValueError('BAD DOGE'), TypeError('BAD DOGE')])"))
