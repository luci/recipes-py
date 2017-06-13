# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'context',
  'path',
  'raw_io',
  'step',
]


# This key is set by "//recipe_engine/unittests/run_test.py" to "default". This
# causes predictable results when run via "run_test", allowing us to test
# correct expression of environment variables in production.
_KEY = 'RECIPE_ENGINE_CONTEXT_TEST'


def RunSteps(api):
  api.step('no env', ['echo', 'hello'])

  with api.context(env={'SOMETHING': '1'}):
    api.step('with env', ['echo', 'hello'])

    with api.context(env={'SOMETHING_ELSE': '0'}):
      api.step('with 2 envs', ['echo', 'hello'])

  # The following tests use "expect_step". In simulation mode, this will always
  # pass. However, when run through "run" or via "unittests/run_test.py", this
  # will process the real output environment variables and assert that they
  # match expectations.
  def expect_step(name, exp):
    result = api.step(
        name,
        ['bash', '-c', 'echo -n $'+_KEY],
        stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(exp),
    )
    assert result.stdout == exp, (
        '%r did not equal expected %r' % (result.stdout, exp))

  expect_step('default', 'default')

  # Can cause envvars to be dropped completely.
  with api.context(env={_KEY: None}):
    expect_step('drop', '')

  pants = api.path['start_dir'].join('pants')
  shirt = api.path['start_dir'].join('shirt')
  with api.context(env={_KEY: 'bar'}):
    expect_step('env step', 'bar')

    base_path = api.path.pathsep.join(['foo', '%('+_KEY+')s', 'bar'])
    with api.context(env={_KEY: base_path}):
      expect_step('env step augmented',
          api.path.pathsep.join(['foo', 'default', 'bar']))

      with api.context(env_prefixes={_KEY: [pants, shirt]}):
        expect_step('env step with prefix',
            api.path.pathsep.join([str(pants), str(shirt), 'foo',
                                   'default', 'bar']))

  # Can set the path of default environment variables.
  with api.context(env_prefixes={_KEY: [shirt]}):
    expect_step('env with default value',
        api.path.pathsep.join([str(shirt), 'default']))

    # When 'env' is also defined, appends it.
    with api.context(env={_KEY: 'foo'}):
      expect_step('env with override value',
            api.path.pathsep.join([str(shirt), 'foo']))

    # When "env" is explicitly cleared, does not append.
    with api.context(env={_KEY: None}):
      expect_step('env with cleared value', str(shirt))

    # When "env" is explicitly empty, does not append.
    with api.context(env={_KEY: ''}):
      expect_step('env with empty value', str(shirt))


def GenTests(api):
  yield api.test('basic')

