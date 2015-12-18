# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
