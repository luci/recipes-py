# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.recipe_modules.recipe_engine.properties.examples.full import InputProps
from PB.recipe_modules.recipe_engine.properties.examples.full import EnvProps

from google.protobuf import struct_pb2, json_format

DEPS = [
  'properties',
  'step',
]

PROPERTIES = InputProps
ENV_PROPERTIES = EnvProps

def RunSteps(api, props, env_props):
  api.step('echo props', ['echo'] + [repr(props)])
  api.step('echo env_props', ['echo'] + [repr(env_props)])

  properties = api.properties.thaw()
  api.step('echo all', ['echo'] + map(repr, sorted(properties.iteritems())))

  # It should behave like a real dictionary.
  assert len(properties) == len(api.properties)
  for k in sorted(api.properties):
    api.step('echo %s' % k, ['echo', repr(api.properties[k])])


def GenTests(api):
  yield (
    api.test('basic')
    + api.properties(
        InputProps(
            test_prop=InputProps.SubMessage(key='value'),
            list=['some', 'strings'],
            # unfortunately, constructing arbitrary Struct fields inline is
            # awkward. Doable... but awkward.
            dict=json_format.ParseDict({
              'cool': 'dictionary',
            }, struct_pb2.Struct()),
            param_name_test='thing',
        ),
        **{
          'arbitrary_property': True,
          '$fake_repo/fake_module': InputProps(
              test_prop=InputProps.SubMessage(key='value'),
          ),
        }
    )
    + api.properties.environ(
        EnvProps(FROM_ENV='mocked_env')
    )
  )

  yield (
    api.test('manual_props')
    + api.properties.environ(FROM_ENV='mocked_env')
  )

  yield (
    api.test('odd_name')
    + api.properties(**{'foo.bar-bam': 'blarp'})
  )

  yield (
    api.test('prop_wrong_type')
    + api.properties(test_prop=True) # wrong type
    + api.expect_exception('ParseError')
  )

  # Deprecated: buildbot "defaults"
  # Some default buildbot configurations.
  yield api.test('buildbot_generic') + api.properties.generic()
  yield (api.test('buildbot_scheduled') +
         api.properties.scheduled())
  yield (api.test('buildbot_git_scheduled') +
         api.properties.git_scheduled())
  yield (api.test('buildbot_tryserver') +
         api.properties.tryserver())
  yield (api.test('buildbot_tryserver_gerrit') +
         api.properties.tryserver(gerrit_project='infra/infra'))
  yield (api.test('buildbot_tryserver_gerrit_override_gerrit') +
         api.properties.tryserver(
            gerrit_project='infra/internal',
            gerrit_url='https://chrome-internal-review.googlesource.com'))
  yield (api.test('buildbot_tryserver_gerrit_override_git') +
         api.properties.tryserver(
            gerrit_project='infra/hidden',
            git_url='https://chrome-internal.googlesource.com/infra/hidden'))
  yield (api.test('buildbot_tryserver_gerrit_override_both') +
         api.properties.tryserver(
            gerrit_project='custom',
            gerrit_url='https://gerrit.my.host',
            git_url='https://git.my.host/custom',
            patch_issue=989898,
            patch_set=3))

  # testing test_api
  try:
    not_a_message = True
    api.properties(not_a_message)
    assert False, ( # pragma: no cover
      'api.properties should only accept proto Messages'
    )
  except ValueError:
    pass

  try:
    not_a_message = True
    api.properties.environ(not_a_message)
    assert False, ( # pragma: no cover
      'api.properties.environ should only accept proto Messages as args'
    )
  except ValueError:
    pass

  try:
    not_an_env_value = ['bad', 'stuff']
    api.properties.environ(ENV_INT=not_an_env_value)
    assert False, ( # pragma: no cover
      'api.properties.environ should only accept simple values'
    )
  except ValueError:
    pass
