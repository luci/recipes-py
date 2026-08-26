# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    context,
    random,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  random: random.API
  step: step.API

from .api import TimeApi as API
from .test_api import TimeTestApi as TEST_API
