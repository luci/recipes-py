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
  if 'maxDiff' in api.properties:
    api.assertions.maxDiff = api.properties['maxDiff']
  try:
    api.assertions.assertEqual(list(range(100)), list(range(99)) + [0])
  except AssertionError as e:
    api.step('AssertionError', [])
    assert 'Set self.maxDiff to None to see it.' not in str(e), (
        'Did not expect self.maxDiff to appear in exception message:\n' +
        str(e))
    modified_message = 'Set assertions.maxDiff to None to see it.'
    if api.properties.get('diff_omitted', False):
      assert modified_message in str(e), (
          'Expected diff to be omitted. Exception message:\n' + str(e))
    else:
      assert modified_message not in str(e), (
          'Expected diff not to be omitted. Exception message:\n' + str(e))


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.properties(maxDiff=None),
      api.post_process(post_process.MustRun, 'AssertionError'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'diff-omitted',
      api.properties(diff_omitted=True),
      api.post_process(post_process.MustRun, 'AssertionError'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
