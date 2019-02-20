# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'assertions',
    'properties',
    'step',
]

def RunSteps(api):
  msg = api.properties.get('msg')
  try:
    api.assertions.assertEqual(0, 1, msg=msg)
  except AssertionError as e:
    api.step('AssertionError', [])
    expected_message = api.properties.get('expected_message')
    if expected_message:
      assert e.message == expected_message, (
          'Expected AssertionError with message: %r\nactual message: %r'
          % (expected_message, e.message))

def GenTests(api):
  yield (
      api.test('basic')
      + api.post_process(post_process.MustRun, 'AssertionError')
      + api.post_process(post_process.DropExpectation)
  )

  yield (
      api.test('custom-message')
      + api.properties(
          msg='{first} should be {second}',
          expected_message='0 should be 1')
      + api.post_process(post_process.MustRun, 'AssertionError')
      + api.post_process(post_process.DropExpectation)
  )
