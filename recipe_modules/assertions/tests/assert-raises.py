# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

DEPS = [
    'assertions',
    'properties',
    'step',
]

class TestException(Exception):
  pass

def RunSteps(api):
  try:
    with api.assertions.assertRaises(TestException) as caught:
      exception_message = api.properties.get('exception_message', '')
      if exception_message:
        raise TestException(exception_message)
  except AssertionError:
    api.step('AssertionError', [])
  else:
    api.step('No AssertionError', [])
    assert str(caught.exception) == exception_message, (
        'Context manager not working, '
        'expected TestException with message: %r\n actual message %r' %
        (exception_message, str(caught.exception)))


def GenTests(api):
  yield api.test(
      'no-exception',
      api.post_process(post_process.MustRun, 'AssertionError'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'exception',
      api.properties(exception_message='fake exception message'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.MustRun, 'No AssertionError'),
      api.post_process(post_process.DropExpectation),
  )
