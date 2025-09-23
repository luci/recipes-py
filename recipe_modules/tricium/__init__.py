# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from . import api as _api

DEPS = [
    'buildbucket',
    'cipd',
    'context',
    'file',
    'findings',
    'json',
    'path',
    'properties',
    'proto',
    'resultdb',
    'step',
]

API = _api.TriciumApi
