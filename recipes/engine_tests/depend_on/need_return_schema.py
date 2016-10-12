# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property, RequireClient
from recipe_engine import config

DEPS = [
    'properties',
]

PROPERTIES = {}

dependency_manager = RequireClient('dependency_manager')

# Missing a RETURN_SCHEMA on purpose

def RunSteps(api):
  dependency_manager.depend_on(
      'engine_tests/depend_on/need_return_schema_helper', {})

def GenTests(api):
  yield (
      api.test('basic') +
      api.expect_exception('ValueError')
  )
