# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    context,
    file,
    futures,
    json,
    path,
    platform,
    properties,
    raw_io,
    step,
    url,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  context: context.API
  file: file.API
  futures: futures.API
  json: json.API
  path: path.API
  platform: platform.API
  properties: properties.API
  raw_io: raw_io.API
  step: step.API
  url: url.API

from .api import CIPDApi as API
from .test_api import CIPDTestApi as TEST_API
