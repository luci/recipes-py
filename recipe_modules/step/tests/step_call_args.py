# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'step',
]


def RunSteps(api):
  try:
    api.step('test step', [{}])
  except AssertionError as e:
    assert str(e) == 'Type <type \'dict\'> is not permitted. cmd is [{}]'


def GenTests(api):
  yield api.test('basic')