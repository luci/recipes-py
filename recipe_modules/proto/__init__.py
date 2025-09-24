# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'raw_io',
]

from .api import ProtoApi as API
from .test_api import ProtoTestApi as TEST_API
