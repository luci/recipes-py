# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi


@dataclass
class DEPS(RecipeScriptApi):
  pass

from .api import ContextApi as API
from .test_api import ContextTestApi as TEST_API
