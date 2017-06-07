# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "context",
  "path",
  "step",
]


def RunSteps(api):
  api.step('no env', ['echo', 'hello'])

  with api.context(env={"SOMETHING": "1"}):
    api.step('with env', ['echo', 'hello'])

    with api.context(env={"SOMETHING_ELSE": "0"}):
      api.step('with 2 envs', ['echo', 'hello'])

  with api.context(env={'FOO': 'bar'}):
    api.step('env step', ['bash', '-c', 'echo $FOO'])

    base_path = 'foo%s%%(FOO)s%sbaz' % (api.path.pathsep, api.path.pathsep)
    with api.context(env={'FOO': base_path}):
      api.step('env step augmented', ['bash', '-c', 'echo $FOO'])

      pants = api.path['start_dir'].join('pants')
      shirt = api.path['start_dir'].join('shirt')
      with api.context(env={'FOO': api.context.Prefix(pants, shirt)}):
        api.step('env step with prefix', ['bash', '-c', 'echo $FOO'])

  # Can set the path of default environment variables.
  with api.context(env={'FOO': api.context.Prefix(shirt)}):
    api.step('env with default value',
             ['bash', '-c', 'echo $FOO'])


def GenTests(api):
  yield api.test('basic')

