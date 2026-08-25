# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


def RunSteps(api: DEPS):
  msg = api.properties.get('msg')
  try:
    api.assertions.assertEqual(0, 1, msg=msg)
  except AssertionError as e:
    api.step('AssertionError', [])
    expected_message = api.properties.get('expected_message')
    if expected_message:
      assert str(e) == expected_message, (
          'Expected AssertionError with message: %r\nactual message: %r' %
          (expected_message, str(e)))


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.post_process(post_process.MustRun, 'AssertionError'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  expected_message = '0 != 1 : 0 should be 1'

  yield api.test(
      'custom-message',
      api.properties(
          msg='{first} should be {second}', expected_message=expected_message),
      api.post_process(post_process.MustRun, 'AssertionError'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
