# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.config import config_item_context, ConfigGroup, Dict, Static
from recipe_engine.config_types import Path


def BaseConfig(PLATFORM, START_DIR, TEMP_DIR, CACHE_DIR, CLEANUP_DIR,
               **_kwargs):
  assert START_DIR[0].endswith(('\\', '/')), START_DIR
  assert TEMP_DIR[0].endswith(('\\', '/')), TEMP_DIR
  assert CACHE_DIR[0].endswith(('\\', '/')), CACHE_DIR
  assert CLEANUP_DIR[0].endswith(('\\', '/')), CLEANUP_DIR
  return ConfigGroup(
      # base path name -> [tokenized absolute path]
      base_paths=Dict(value_type=tuple),

      # dynamic path name -> Path object (referencing one of the base_paths)
      dynamic_paths=Dict(value_type=(Path, type(None))),
      PLATFORM=Static(PLATFORM),
      START_DIR=Static(tuple(START_DIR)),
      TEMP_DIR=Static(tuple(TEMP_DIR)),
      CACHE_DIR=Static(tuple(CACHE_DIR)),
      CLEANUP_DIR=Static(tuple(CLEANUP_DIR)),
  )


config_ctx = config_item_context(BaseConfig)


@config_ctx(is_root=True)
def BASE(c):
  c.base_paths['start_dir'] = c.START_DIR
  c.base_paths['tmp_base'] = c.TEMP_DIR
  c.base_paths['cache'] = c.CACHE_DIR
  c.base_paths['cleanup'] = c.CLEANUP_DIR
  c.dynamic_paths['checkout'] = None
