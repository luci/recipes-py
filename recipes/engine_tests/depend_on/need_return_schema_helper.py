# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'properties',
]

PROPERTIES = {}

# Missing a RETURN_SCHEMA on purpose

def RunSteps(api):
  pass

def GenTests(api):
  yield (
      api.test('basic')
  )
