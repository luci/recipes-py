# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    cipd,
    file,
    path,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  cipd: cipd.API
  file: file.API
  path: path.API
  step: step.API

from .api import BcidVerifierApi as API
