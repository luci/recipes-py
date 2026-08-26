# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    resultdb,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  resultdb: resultdb.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  resultdb: resultdb.TEST_API


def RunSteps(api: DEPS):
  sub_invs = api.resultdb.get_included_invocations(
      inv_name='invocations/build-8831400474790691137')
  api.assertions.assertIn('inv1', sub_invs)
  api.assertions.assertIn('inv2', sub_invs)
  api.assertions.assertEqual(2, len(sub_invs))


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.resultdb.get_included_invocations(['inv1', 'inv2']),
      api.post_process(DropExpectation),
  )
