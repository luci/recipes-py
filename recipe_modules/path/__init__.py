# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
  '$recipe_engine/path': Property(
    help='Properties specifically for the recipe_engine path module.',
    param_name='path_properties',
    kind=ConfigGroup(
      # The absolute path to the temporary directory that the recipe should use.
      temp_dir=Single(str),
      # The absolute path to the cache directory that the recipe should use.
      cache_dir=Single(str),
      # The absolute path to the cleanup directory that the recipe should use.
      cleanup_dir=Single(str),
    ), default={},
  )
}

DEPS = [
    'recipe_engine/context',
    'recipe_engine/warning',
]

from .api import PathApi as API
from .test_api import PathTestApi as TEST_API
