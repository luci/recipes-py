# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'properties',
]

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
    '$recipe_engine/isolated': Property(
        help='Properties specifically for the isolated module',
        param_name='isolated_properties',
        kind=ConfigGroup(
          server=Single(str),
        ),
        default={},
      ),
}
