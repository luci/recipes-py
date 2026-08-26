# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    raw_io,
    step,
    warning,
)


@dataclass
class DEPS(RecipeScriptApi):
  raw_io: raw_io.API
  step: step.API
  warning: warning.API

from .api import JsonApi as API
from .test_api import JsonTestApi as TEST_API
