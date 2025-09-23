# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from . import api as _api
from . import test_api as _test_api

DEPS = [
    'context',
    'futures',
    'json',
    'raw_io',
    'step',
    'time',
    'uuid',
]

API = _api.ResultDBAPI
TEST_API = _test_api.ResultDBTestApi
