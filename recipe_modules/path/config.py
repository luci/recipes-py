# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.config import config_item_context, ConfigGroup, Dict, Static
from recipe_engine.config_types import Path

def BaseConfig(PLATFORM, CURRENT_WORKING_DIR, TEMP_DIR, **_kwargs):
  assert CURRENT_WORKING_DIR[0].endswith(('\\', '/'))
  assert TEMP_DIR[0].endswith(('\\', '/'))
  return ConfigGroup(
    # base path name -> [tokenized absolute path]
    base_paths    = Dict(value_type=tuple),

    # dynamic path name -> Path object (referencing one of the base_paths)
    dynamic_paths = Dict(value_type=(Path, type(None))),

    PLATFORM = Static(PLATFORM),
    CURRENT_WORKING_DIR = Static(tuple(CURRENT_WORKING_DIR)),
    TEMP_DIR = Static(tuple(TEMP_DIR)),
  )

config_ctx = config_item_context(BaseConfig)

@config_ctx(is_root=True)
def BASE(c):
  c.base_paths['cwd'] = c.CURRENT_WORKING_DIR
  c.base_paths['tmp_base'] = c.TEMP_DIR
  c.dynamic_paths['checkout'] = None
