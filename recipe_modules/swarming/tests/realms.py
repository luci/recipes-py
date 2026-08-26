# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    buildbucket,
    context,
    step,
    swarming,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  buildbucket: buildbucket.API
  context: context.API
  step: step.API
  swarming: swarming.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API


def RunSteps(api: DEPS):
  def basic_request():
    request = api.swarming.task_request()
    return request.with_slice(0, request[0].
        with_command(['echo', 'hi']).
        with_dimensions(pool='example.pool', os='Debian'))

  with api.context(realm='some:realm'):
    request = basic_request().with_resultdb()
    api.assertions.assertEqual('some:realm', request.realm)
    request.to_jsonish()  # doesn't blow up

  with api.context(realm=''):
    request = basic_request().with_resultdb()
    api.assertions.assertEqual(None, request.realm)
    res = request.to_jsonish()
    # Picks up builder's realm.
    api.assertions.assertEqual('proj:buck', res['realm'])


def GenTests(api: TEST_DEPS):
  yield (
      api.test('basic') +
      api.buildbucket.ci_build(project='proj', bucket='buck') +
      api.post_process(DropExpectation))
