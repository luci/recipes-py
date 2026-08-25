# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    buildbucket,
    cv,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  buildbucket: buildbucket.API
  cv: cv.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  cv: cv.TEST_API
  properties: properties.TEST_API


def RunSteps(api: DEPS):
  if 'raises' in api.properties:
    with api.assertions.assertRaises(api.cv.CQInactive):
      api.cv.ordered_gerrit_changes
    return

  api.assertions.assertEqual(
      ' '.join(str(g.change) for g in api.cv.ordered_gerrit_changes),
      api.properties['expected_cls'])


def GenTests(api: TEST_DEPS):
  yield (
      api.test('cq-run') + api.cv(run_mode=api.cv.FULL_RUN)
      # api.buildbucket.gerrit_changes must be simulated
      # to use api.cv.ordered_gerrit_changes.
      + api.buildbucket.try_build(change_number=123) +
      api.properties(expected_cls='123') +
      api.post_process(post_process.DropExpectation))
  yield (api.test('not-a-cq-run') + api.properties(raises=True) +
         api.post_process(post_process.DropExpectation))
