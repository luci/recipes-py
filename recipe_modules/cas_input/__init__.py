# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.cas_input import properties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    cas,
    path,
)


@dataclass
class DEPS(RecipeScriptApi):
  cas: cas.API
  path: path.API

PROPERTIES = properties.InputProperties

from .api import CasInputApi as API
