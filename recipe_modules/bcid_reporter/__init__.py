# Copyright 2022 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    cipd,
    context,
    file,
    path,
    properties,
    step,
    time,
)


@dataclass
class DEPS(RecipeScriptApi):
  cipd: cipd.API
  context: context.API
  file: file.API
  path: path.API
  properties: properties.API
  step: step.API
  time: time.API

from .api import BcidReporterApi as API
from .test_api import BcidReporterTestApi as TEST_API
