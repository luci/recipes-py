# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    context,
    futures,
    json,
    raw_io,
    step,
    time,
    uuid,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  futures: futures.API
  json: json.API
  raw_io: raw_io.API
  step: step.API
  time: time.API
  uuid: uuid.API

from .api import ResultDBAPI as API
from .test_api import ResultDBTestApi as TEST_API
