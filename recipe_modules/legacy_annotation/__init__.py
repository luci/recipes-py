# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'cipd',
  'context',
  'step',
]

from .api import LegacyAnnotationApi as API
from .test_api import LegacyAnnotationTestApi as TEST_API
