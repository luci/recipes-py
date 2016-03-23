# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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

def test_name(args):  # pragma: no cover
  if args['CURRENT_WORKING_DIR'][0] == '/':
    return 'posix'
  else:
    return 'windows'

config_ctx = config_item_context(BaseConfig)

@config_ctx(is_root=True)
def BASE(c):
  c.base_paths['cwd'] = c.CURRENT_WORKING_DIR
  c.base_paths['tmp_base'] = c.TEMP_DIR

@config_ctx()
def buildbot(c):
  c.base_paths['root'] = c.CURRENT_WORKING_DIR[:-4]
  c.base_paths['slave_build'] = c.CURRENT_WORKING_DIR
  c.base_paths['git_cache'] = c.base_paths['root'] + (
      'build', 'slave', 'cache_dir')
  c.base_paths['goma_cache'] = c.base_paths['root'] + (
      'build', 'slave', 'goma_cache')
  for token in ('build_internal', 'build', 'depot_tools'):
    c.base_paths[token] = c.base_paths['root'] + (token,)
  c.dynamic_paths['checkout'] = None

@config_ctx(includes=['buildbot'])
def swarming(c):
  c.base_paths['slave_build'] = (
      c.CURRENT_WORKING_DIR[:1] +
      ('b', 'fake_build', 'slave', 'fake_slave', 'build'))

@config_ctx()
def kitchen(c):
  c.base_paths['root'] = c.CURRENT_WORKING_DIR
  c.base_paths['slave_build'] = c.CURRENT_WORKING_DIR
  # TODO(phajdan.jr): have one cache dir, let clients append suffixes.
  # TODO(phajdan.jr): set persistent cache path for remaining platforms.
  if c.PLATFORM == 'linux':
    c.base_paths['git_cache'] = ('b', 'swarm_slave', 'cache', 'git_cache')
    c.base_paths['goma_cache'] = ('b', 'swarm_slave', 'cache', 'goma_cache')
  else:
    c.base_paths['git_cache'] = c.base_paths['root'] + ('cache_dir',)
    c.base_paths['goma_cache'] = c.base_paths['root'] + ('goma_cache',)
  c.dynamic_paths['checkout'] = None
