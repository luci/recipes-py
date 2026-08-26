# Copyright 2024 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    proto,
    resultdb,
    step,
    uuid,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  proto: proto.API
  resultdb: resultdb.API
  step: step.API
  uuid: uuid.API

from .api import FindingsAPI as API
