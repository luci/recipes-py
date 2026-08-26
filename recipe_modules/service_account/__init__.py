# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    path,
    platform,
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  path: path.API
  platform: platform.API
  raw_io: raw_io.API
  step: step.API

from .api import ServiceAccountApi as API
