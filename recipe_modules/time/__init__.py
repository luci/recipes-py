# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'context',
    'step',
    'random',
]

from .api import TimeApi as API
from .test_api import TimeTestApi as TEST_API
