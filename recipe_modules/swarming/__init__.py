# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.swarming import properties

DEPS = [
    'buildbucket',  # TODO(crbug.com/1122808): Remove this dependency.
    'cas',
    'cipd',
    'context',
    'json',
    'path',
    'properties',
    'raw_io',
    'step',
]

ENV_PROPERTIES = properties.EnvProperties

from .api import SwarmingApi as API
from .test_api import SwarmingTestApi as TEST_API
