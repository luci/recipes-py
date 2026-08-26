# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from RECIPE_MODULES.recipe_engine import path


@dataclass
class DEPS(RecipeScriptApi):
  path: path.API

from .api import RawIOApi as API
from .test_api import RawIOTestApi as TEST_API
