# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from . import api as _api
from . import test_api as _test_api

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

API = _api.BuildbucketApi
TEST_API = _test_api.BuildbucketTestApi
