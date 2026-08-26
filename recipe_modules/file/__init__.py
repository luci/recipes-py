# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    json,
    path,
    proto,
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  json: json.API
  path: path.API
  proto: proto.API
  raw_io: raw_io.API
  step: step.API

from .api import FileApi as API
from .test_api import FileTestApi as TEST_API
