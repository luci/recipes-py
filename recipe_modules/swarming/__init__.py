# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

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

from recipe_engine.config import ConfigGroup, Single
from recipe_engine.recipe_api import Property

PROPERTIES = {
    '$recipe_engine/swarming': Property(
        help='Properties specifically for the swarming module',
        param_name='swarming_properties',
        kind=ConfigGroup(
          server=Single(str),
          version=Single(str),
        ),
        default={},
      ),
}
