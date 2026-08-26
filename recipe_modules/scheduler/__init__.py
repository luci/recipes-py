# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from past.builtins import basestring

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, List, Single

from PB.recipe_modules.recipe_engine.scheduler import (
    properties as properties_pb,
)

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    buildbucket,
    json,
    platform,
    raw_io,
    step,
    time,
)


@dataclass
class DEPS(RecipeScriptApi):
  buildbucket: buildbucket.API
  json: json.API
  platform: platform.API
  raw_io: raw_io.API
  step: step.API
  time: time.API

PROPERTIES = properties_pb.InputProperties

from .api import SchedulerApi as API
from .test_api import SchedulerTestApi as TEST_API
