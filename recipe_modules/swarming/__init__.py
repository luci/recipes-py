# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.recipe_modules.recipe_engine.swarming import properties


DEPS = [
  'cipd',
  'context',
  'isolated',
  'json',
  'path',
  'properties',
  'runtime',
  'raw_io',
  'step',
]

PROPERTIES = properties.InputProperties
ENV_PROPERTIES = properties.EnvProperties
