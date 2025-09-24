# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'recipe_engine/warning',
]

from .api import PropertiesApi as API
from .test_api import PropertiesTestApi as TEST_API
