# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import recipe_test_api

class TimeTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def seed(now):
    """Set the starting time for the clock in api.time."""
    return now

  @recipe_test_api.mod_test_data
  @staticmethod
  def step(step):
    """Set the number of seconds the simulated clock will advance for each
    api.time.time() or api.time.utcnow() is called.
    """
    return step
