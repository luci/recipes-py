# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.runtime import properties

from . import api as _api
from . import test_api as _test_api

PROPERTIES = properties.InputProperties

API = _api.RuntimeApi
TEST_API = _test_api.RuntimeTestApi
