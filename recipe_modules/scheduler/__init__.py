# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from past.builtins import basestring

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, List, Single

from PB.recipe_modules.recipe_engine.scheduler import (
    properties as properties_pb,
)

DEPS = [
  'buildbucket',
  'json',
  'platform',
  'raw_io',
  'step',
  'time',
]

PROPERTIES = properties_pb.InputProperties

from .api import SchedulerApi as API
from .test_api import SchedulerTestApi as TEST_API
