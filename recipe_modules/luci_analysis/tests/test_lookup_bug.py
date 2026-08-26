# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for lookup_bug."""

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    json,
    luci_analysis,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  json: json.API
  luci_analysis: luci_analysis.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  json: json.TEST_API
  luci_analysis: luci_analysis.TEST_API


def RunSteps(api: DEPS):
  with api.step.nest('nest_parent') as presentation:
    bug = 'chromium/123'
    rules = api.luci_analysis.lookup_bug(bug)
    presentation.logs['rules'] = api.json.dumps(rules)


from recipe_engine import post_process


def GenTests(api: TEST_DEPS):
  yield api.test(
      'base',
      api.luci_analysis.lookup_bug([
          'projects/chromium/rules/00000000000000000000ffffffffffff',
      ],
                                   'chromium/123',
                                   parent_step_name='nest_parent'),
      api.post_check(lambda check, steps: check(
          api.json.loads(steps['nest_parent'].logs['rules']) == [
              'projects/chromium/rules/00000000000000000000ffffffffffff',
          ])),
      api.post_process(post_process.DropExpectation),
  )
