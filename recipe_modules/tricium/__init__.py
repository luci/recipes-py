# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

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

from .api import TriciumApi as API
