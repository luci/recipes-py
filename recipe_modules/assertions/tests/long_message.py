# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'assertions',
    'step',
]

def RunSteps(api):
  api.assertions.longMessage = True
  try:
    api.assertions.assertEqual(0, 1, 'custom message')
  except AssertionError as e:
    api.step('AssertionError', [])
    expected_message = '0 != 1 : custom message'
    assert e.message == expected_message, (
        'Expected AssertionError with message: %r\nactual message: %r'
        % (expected_message, e.message))

def GenTests(api):
  yield (
      api.test('basic')
      + api.post_process(post_process.MustRun, 'AssertionError')
      + api.post_process(post_process.DropExpectation)
  )
