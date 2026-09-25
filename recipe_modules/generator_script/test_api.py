# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from recipe_engine import recipe_test_api

class GeneratorScriptTestApi(recipe_test_api.RecipeTestApi):
  def __call__(
      self, script_name: str, *steps: Mapping[str, Any]
  ) -> recipe_test_api.TestData:
    assert all(isinstance(s, dict) for s in steps)
    return self.step_data(
      'gen step(%s)' % script_name,
      self.m.json.output(list(steps))
    )
