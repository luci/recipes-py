# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2

from . import api as _api
from . import test_api as _test_api

DEPS = [
    'cv',
    'properties',
    'warning',
]

PROPERTIES = cq_pb2.Input

API = _api.CQApi
TEST_API = _test_api.CQTestApi
