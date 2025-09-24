# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'context',
    'futures',
    'json',
    'raw_io',
    'step',
    'time',
    'uuid',
]

from .api import ResultDBAPI as API
from .test_api import ResultDBTestApi as TEST_API
