# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'context',
  'json',
  'path',
  'step',
]

from .api import GeneratorScriptApi as API
from .test_api import GeneratorScriptTestApi as TEST_API
