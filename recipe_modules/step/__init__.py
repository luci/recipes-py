# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, List

DEPS = [
  "context",
  "path",
  "platform",
  "proto",
]

PROPERTIES = {
  '$recipe_engine/step': Property(
    help="Properties for the recipe_engine/step module",
    param_name="step_properties",
    kind=ConfigGroup(
      # A list of PATH elements to prefix onto the PATH for every step.
      prefix_path=List(str),
    ), default={
      'prefix_path': [],
    }),
}
