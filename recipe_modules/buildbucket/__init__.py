# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'json',
  'path',
  'platform',
  'raw_io',
  'resultdb',
  'runtime',
  'step',
  'uuid',
  'warning',
]

from PB.recipe_modules.recipe_engine.buildbucket import properties

PROPERTIES = properties.InputProperties
# Deprecated.
GLOBAL_PROPERTIES = properties.LegacyInputProperties

from .api import BuildbucketApi as API
from .test_api import BuildbucketTestApi as TEST_API
