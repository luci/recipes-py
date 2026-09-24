# Copyright 2022 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations
from collections.abc import Callable, Mapping
from recipe_engine import post_process_inputs

from collections.abc import Iterator
from recipe_engine import recipe_test_api

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  step: step.API


def RunSteps(api: DEPS) -> None:
  step = api.step('hostname', ['echo', api.buildbucket.host])
  step.presentation.tags[u'k1'] = u'v1'
  step.presentation.tags[u'k2'] = u'v2'


def GenTests(api: RecipeTestApi) -> Iterator[recipe_test_api.TestData]:
  def assert_pairs(
      check: Callable[..., bool],
      steps: Mapping[str, post_process_inputs.Step],
  ) -> None:
    check(steps["hostname"].tags["k1"] == "v1")
    check(steps["hostname"].tags["k2"] == "v2")

  yield api.test('basic') + api.post_check(assert_pairs)
