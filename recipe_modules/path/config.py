# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave.recipe_config import config_item_context, ConfigGroup, Dict, Static
from slave.recipe_config_types import Path

def BaseConfig(CURRENT_WORKING_DIR, TEMP_DIR, **_kwargs):
  assert CURRENT_WORKING_DIR[0].endswith(('\\', '/'))
  assert TEMP_DIR[0].endswith(('\\', '/'))
  return ConfigGroup(
    # base path name -> [tokenized absolute path]
    base_paths    = Dict(value_type=tuple),

    # dynamic path name -> Path object (referencing one of the base_paths)
    dynamic_paths = Dict(value_type=(Path, type(None))),

    CURRENT_WORKING_DIR = Static(tuple(CURRENT_WORKING_DIR)),
    TEMP_DIR = Static(tuple(TEMP_DIR)),
  )

VAR_TEST_MAP = {
  'CURRENT_WORKING_DIR': (
    ['/', 'b', 'build', 'slave', 'fake_slave', 'build'],
    ['E:\\', 'build', 'slave', 'fake_slave', 'build'],
  ),
  'TEMP_DIR': (
    ['/', 'fake_tmp'],
    ['C:\\', 'fake_temp'],
  ),
}

def test_name(args):
  if args['CURRENT_WORKING_DIR'][0] == '/':
    return 'posix'
  else:
    return 'windows'

config_ctx = config_item_context(BaseConfig, VAR_TEST_MAP, test_name)

@config_ctx(is_root=True)
def BASE(c):
  c.base_paths['cwd'] = c.CURRENT_WORKING_DIR
  c.base_paths['tmp_base'] = c.TEMP_DIR

@config_ctx()
def buildbot(c):
  c.base_paths['root'] = c.CURRENT_WORKING_DIR[:-4]
  c.base_paths['slave_build'] = c.CURRENT_WORKING_DIR
  for token in ('build_internal', 'build', 'depot_tools'):
    c.base_paths[token] = c.base_paths['root'] + (token,)
  c.dynamic_paths['checkout'] = None

