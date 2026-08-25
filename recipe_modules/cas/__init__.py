# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.cas import properties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    cipd,
    context,
    file,
    json,
    path,
    raw_io,
    runtime,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  cipd: cipd.API
  context: context.API
  file: file.API
  json: json.API
  path: path.API
  raw_io: raw_io.API
  runtime: runtime.API
  step: step.API

ENV_PROPERTIES = properties.EnvProperties

from .api import CasApi as API
