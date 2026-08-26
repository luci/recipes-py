# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.led import properties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    cipd,
    context,
    json,
    path,
    proto,
    step,
    swarming,
)


@dataclass
class DEPS(RecipeScriptApi):
  cipd: cipd.API
  context: context.API
  json: json.API
  path: path.API
  proto: proto.API
  step: step.API
  swarming: swarming.API

PROPERTIES = properties.InputProperties

from .api import LedApi as API
from .test_api import LedTestApi as TEST_API
