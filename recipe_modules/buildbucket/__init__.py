# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    json,
    path,
    platform,
    raw_io,
    resultdb,
    runtime,
    step,
    uuid,
    warning,
)


@dataclass
class DEPS(RecipeScriptApi):
  json: json.API
  path: path.API
  platform: platform.API
  raw_io: raw_io.API
  resultdb: resultdb.API
  runtime: runtime.API
  step: step.API
  uuid: uuid.API
  warning: warning.API

from PB.recipe_modules.recipe_engine.buildbucket import properties

PROPERTIES = properties.InputProperties
# Deprecated.
GLOBAL_PROPERTIES = properties.LegacyInputProperties

from .api import BuildbucketApi as API
from .test_api import BuildbucketTestApi as TEST_API
