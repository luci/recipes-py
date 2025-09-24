# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'path',
]

from .api import RawIOApi as API
from .test_api import RawIOTestApi as TEST_API
