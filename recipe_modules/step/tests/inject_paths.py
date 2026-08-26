# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    context,
    path,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  path: path.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


def RunSteps(api: DEPS):
  with api.context(env={'FOO': 'bar'}):
    api.step('test step (no env)', ['echo', 'hi'])

  with api.context(env={'PATH': 'something'}):
    api.step('test step (env)', ['echo', 'hi'])

  with api.context(env={
      'PATH': api.path.pathsep.join(('something', '%(PATH)s'))}):
    api.step('test step (env, $PATH)', ['echo', 'hi'])


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
  yield api.test('with_value') + api.properties(**{
    '$recipe_engine/step': {
      'prefix_path': ['foo', 'bar'],
    }
  })
