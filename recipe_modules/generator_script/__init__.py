# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi

from RECIPE_MODULES.recipe_engine import (
    context,
    json,
    path,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  json: json.API
  path: path.API
  step: step.API

from .api import GeneratorScriptApi as API
from .test_api import GeneratorScriptTestApi as TEST_API
