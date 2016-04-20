# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
  'properties',
  'step',
]

PROPERTIES = {
  'test_prop': Property(),
}

def RunSteps(api, test_prop):
  api.step('echo', ['echo'] + [repr(test_prop)])

  properties = api.properties.thaw()
  api.step('echo all', ['echo'] +
      [repr(list(sorted(api.properties.thaw().iteritems())))])

  # It should behave like a real dictionary.
  assert len(properties) == len(api.properties)
  for k in api.properties:
    assert k in properties
    # We would assert that v is there too, but sometimes it's frozen...


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

  # Some default buildbot configurations.
  yield api.test('buildbot_generic') + api.properties.generic(test_prop=None)
  yield (api.test('buildbot_scheduled') +
         api.properties.scheduled(test_prop=None))
  yield (api.test('buildbot_git_scheduled') +
         api.properties.git_scheduled(test_prop=None))
  yield (api.test('buildbot_tryserver') +
         api.properties.tryserver(test_prop=None))
  yield (api.test('buildbot_tryserver_gerrit') +
         api.properties.tryserver_gerrit(full_project_name='infra/infra',
                                         test_prop=None))
