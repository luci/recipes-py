# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single


PROPERTIES = {
  '$recipe_engine/runtime': Property(
    help='Properties specifically for the runtime module',
    param_name='properties',
    kind=ConfigGroup(
      # DEPRECATED (always True)
      is_luci=Single(bool, empty_val=True),

      # Whether build is running in experimental mode.
      is_experimental=Single(bool),
    ),
    default={},
  ),
}
