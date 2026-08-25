# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

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


def RunSteps(api: DEPS):
  tags = api.buildbucket.tags(k1='v1', k2=['v2', 'v2_1'])
  api.buildbucket.add_tags_to_current_build(tags)
  api.buildbucket.hide_current_build_in_gerrit()


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
