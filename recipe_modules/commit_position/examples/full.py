# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'commit_position',
    'step',
]


def RunSteps(api):
  expected = ('refs/heads/main', 12345)
  actual = api.commit_position.parse('refs/heads/main@{#12345}')
  assert actual == expected, (actual, expected)

  try:
    api.commit_position.parse('main@{#12345}')
  except ValueError as ex:
    ex_msg = ex.message
  step_res = api.step('invalid', cmd=None)
  step_res.presentation.logs['ex'] = ex.message.splitlines()

  expected = 'refs/heads/main@{#12345}'
  actual = api.commit_position.format('refs/heads/main', 12345)
  assert actual == expected, (actual, expected)

def GenTests(api):
  yield api.test('basic')
