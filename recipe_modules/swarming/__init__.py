# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.swarming import properties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    cas,
    cipd,
    context,
    json,
    path,
    properties as properties_rm,
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  cas: cas.API
  cipd: cipd.API
  context: context.API
  json: json.API
  path: path.API
  properties: properties_rm.API
  raw_io: raw_io.API
  step: step.API

ENV_PROPERTIES = properties.EnvProperties

from .api import SwarmingApi as API
from .test_api import SwarmingTestApi as TEST_API
