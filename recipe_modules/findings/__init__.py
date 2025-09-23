# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from . import api as _api

DEPS = [
    'buildbucket',
    'proto',
    'resultdb',
    'step',
    'uuid',
]

API = _api.FindingsAPI
