# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [ ]

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single

PROPERTIES = {
  '$recipe_engine/random': Property(
    help='Properties to control the `random` module.',
    param_name='module_properties',
    kind=ConfigGroup(
      # help='A seed to be passed to random.'
      seed=Single(int, required=False),
    ), default={},
  )
}
