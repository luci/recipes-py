# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.step import properties as properties_pb

PROPERTIES = properties_pb.InputProperties

DEPS = [
    "context",
    "path",
    "platform",
    "proto",
    "warning",
]

from .api import StepApi as API
from .test_api import StepTestApi as TEST_API
