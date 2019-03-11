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
  if 'maxDiff' in api.properties:
    api.assertions.maxDiff = api.properties['maxDiff']
  try:
    api.assertions.assertEqual(range(100), range(99) + [0])
  except AssertionError as e:
    api.step('AssertionError', [])
    assert 'Set self.maxDiff to None to see it.' not in e.message, (
        'Did not expect self.maxDiff to appear in exception message:\n'
        + e.message)
    modified_message = 'Set assertions.maxDiff to None to see it.'
    if api.properties.get('diff_omitted', False):
      assert modified_message in e.message, (
          'Expected diff to be omitted. Exception message:\n'
          + e.message)
    else:
      assert modified_message not in e.message, (
          'Expected diff not to be omitted. Exception message:\n'
          + e.message)

def GenTests(api):
  yield (
      api.test('basic')
      + api.properties(maxDiff=None)
      + api.post_process(post_process.MustRun, 'AssertionError')
      + api.post_process(post_process.DropExpectation)
  )

  yield (
      api.test('diff-omitted')
      + api.properties(diff_omitted=True)
      + api.post_process(post_process.MustRun, 'AssertionError')
      + api.post_process(post_process.DropExpectation)
  )
