# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    json,
    path,
    platform,
    raw_io,
    resultdb,
    runtime,
    step,
    uuid,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  json: json.API
  path: path.API
  platform: platform.API
  raw_io: raw_io.API
  resultdb: resultdb.API
  runtime: runtime.API
  step: step.API
  uuid: uuid.API

from .api import MiloApi as API
