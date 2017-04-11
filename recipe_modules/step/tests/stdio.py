# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'raw_io',
  'step',
]


def RunSteps(api):
  # Read command's stdout and stderr.
  step_result = api.step('echo', ['echo', 'Hello World'],
      stdout=api.raw_io.output(),
      stderr=api.raw_io.output())

  # Pass stuff to command's stdin, read it from stdout.
  step_result = api.step('cat', ['cat'],
      stdin=api.raw_io.input_text(data='hello'),
      stdout=api.raw_io.output('out'))

  # Example of auto-mocking stdout. '\n' appended to mock 'echo' behavior.
  step_result = api.step(
      'automock',
      ['echo', 'huh'],
      stdout=api.raw_io.output('out'),
      step_test_data=(
          lambda: api.raw_io.test_api.stream_output('huh\n')))
  assert step_result.stdout == 'huh\n'


def GenTests(api):
  yield api.test('basic')
