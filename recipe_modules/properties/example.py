# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from infra.libs.infra_types import thaw
from recipe_engine.recipe_api import Property

DEPS = ['properties', 'step']

PROPERTIES = {
  'test_prop': Property(),
}

def RunSteps(api, test_prop):
  api.step('echo', ['echo'] + [repr(test_prop)])
  api.step('echo all', ['echo'] + [repr(api.properties.thaw())])

def GenTests(api):
  yield api.test('basic') + api.properties(
    test_prop={'key': 'value'})
  yield api.test('lists') + api.properties(
    test_prop={'key': ['value', ['value']]})
  yield api.test('dicts') + api.properties(
    test_prop={'key': {'key': 'value', 'other_key': {'key': 'value'}}})

  yield (
      api.test('exception') +
      api.expect_exception('ValueError')
  )

