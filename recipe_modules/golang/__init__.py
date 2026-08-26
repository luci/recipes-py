# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    cipd,
    context,
    path,
    platform,
)


@dataclass
class DEPS(RecipeScriptApi):
  cipd: cipd.API
  context: context.API
  path: path.API
  platform: platform.API

from .api import GolangApi as API
