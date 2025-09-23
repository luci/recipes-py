# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from past.builtins import basestring

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, List, Single

from . import api as _api
from . import test_api as _test_api

DEPS = [
  'buildbucket',
  'json',
  'platform',
  'raw_io',
  'step',
  'time',
]

PROPERTIES = {
  '$recipe_engine/scheduler': Property(
      help='Internal property to initialize scheduler module',
      param_name='init_state',
      kind=ConfigGroup(
          hostname=Single(basestring, required=False),
          job=Single(basestring, required=False),
          invocation=Single(basestring, required=False),
          # A list of scheduler triggers that triggered the current build.
          # A trigger is JSON-formatted dict of a scheduler.Trigger protobuf
          # message.
          triggers=List(dict),
      ),
      default={},
  ),
}

API = _api.SchedulerApi
TEST_API = _test_api.SchedulerTestApi
