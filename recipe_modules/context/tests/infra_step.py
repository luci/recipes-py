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
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  path: path.API
  step: step.API


def RunSteps(api: DEPS):
  was_infra_failure = None
  try:
    api.step('boom', ['echo', 'hello'])
  except api.step.InfraFailure:  # pragma: no cover
    assert False, 'impossible'
  except api.step.StepFailure:
    was_infra_failure = False

  assert was_infra_failure is False, 'got: %r' % was_infra_failure

  with api.context(infra_steps=True):
    was_infra_failure = None
    try:
      api.step('boom 2', ['echo', 'hello', 'subdir'])
    except api.step.InfraFailure:
      was_infra_failure = True
    except api.step.StepFailure:  # pragma: no cover
      assert False, 'impossible'
    assert was_infra_failure is True


def GenTests(api: RecipeTestApi):
  yield (
    api.test('basic')
    + api.step_data('boom', retcode=1)
    + api.step_data('boom 2', retcode=1)
  )
