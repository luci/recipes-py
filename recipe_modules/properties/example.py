# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
  'properties',
  'step',
]

PROPERTIES = {
  'test_prop': Property(),
  'foo.bar-bam': Property(param_name='param_name_test'),
}

def RunSteps(api, test_prop, param_name_test):
  api.step('echo', ['echo'] + [repr(test_prop), repr(param_name_test)])

  properties = api.properties.thaw()
  api.step('echo all', ['echo'] + map(repr, sorted(properties.iteritems())))

  # It should behave like a real dictionary.
  assert len(properties) == len(api.properties)
  for k in api.properties:
    assert k in properties
    # We would assert that v is there too, but sometimes it's frozen...


def GenTests(api):
  pd = {'foo.bar-bam': 'thing'}
  yield api.test('basic') + api.properties(
    test_prop={'key': 'value'}, **pd)
  yield api.test('lists') + api.properties(
    test_prop={'key': ['value', ['value']]}, **pd)
  yield api.test('dicts') + api.properties(
    test_prop={'key': {'key': 'value', 'other_key': {'key': 'value'}}},
    **pd)

  yield (
      api.test('exception') +
      api.expect_exception('ValueError')
  )

  # Some default buildbot configurations.
  pd['test_prop'] = None
  yield api.test('buildbot_generic') + api.properties.generic(**pd)
  yield (api.test('buildbot_scheduled') +
         api.properties.scheduled(**pd))
  yield (api.test('buildbot_git_scheduled') +
         api.properties.git_scheduled(**pd))
  yield (api.test('buildbot_tryserver') +
         api.properties.tryserver(**pd))
  yield (api.test('buildbot_tryserver_gerrit') +
         api.properties.tryserver(gerrit_project='infra/infra', **pd))
  yield (api.test('buildbot_tryserver_gerrit_override_gerrit') +
         api.properties.tryserver(
            gerrit_project='infra/internal',
            gerrit_url='https://chrome-internal-review.googlesource.com',
            **pd))
  yield (api.test('buildbot_tryserver_gerrit_override_git') +
         api.properties.tryserver(
            gerrit_project='infra/hidden',
            git_url='https://chrome-internal.googlesource.com/infra/hidden',
            **pd))
  yield (api.test('buildbot_tryserver_gerrit_override_both') +
         api.properties.tryserver(
            gerrit_project='custom',
            gerrit_url='https://gerrit.my.host',
            git_url='https://git.my.host/custom',
            patch_issue=989898,
            patch_set=3,
            **pd))
