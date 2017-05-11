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

def GenTests(api):
  yield api.test('basic')

