# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.path import properties as properties_pb

PROPERTIES = properties_pb.InputProperties

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import (
    context,
    warning,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  warning: warning.API

from .api import PathApi as API
from .test_api import PathTestApi as TEST_API
