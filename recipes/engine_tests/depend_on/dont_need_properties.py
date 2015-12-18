# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'properties',
]

def RunSteps(api):
  api.depend_on('engine_tests/depend_on/dont_need_properties_helper', {})

def GenTests(api):
  yield (
      api.test('basic') +
      api.depend_on('engine_tests/depend_on/dont_need_properties_helper', {}, {'result': 0})
  )
