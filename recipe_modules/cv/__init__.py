# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  properties: properties.API
  step: step.API

PROPERTIES = cq_pb2.Input

from .api import CVApi as API
from .test_api import CVTestApi as TEST_API
