# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'properties',
]

PROPERTIES = {}

RETURN_SCHEMA = config.ReturnSchema(
    result=config.Single(int),
)

def RunSteps(api):
  res = api.depend_on('engine_tests/depend_on/bottom', {'number': 'lalala'})

def GenTests(api):
  yield (
      api.test('basic') +
      api.properties() +
      api.expect_exception('TypeError')
  )
