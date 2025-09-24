# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.cv.api.recipe.v1 import cq as cq_pb2

DEPS = [
    'buildbucket',
    'properties',
    'step',
]

PROPERTIES = cq_pb2.Input

from .api import CVApi as API
from .test_api import CVTestApi as TEST_API
