# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'raw_io',
  'step',
  'step_history',
]


def GenSteps(api):
  # Read command's stdout and stderr.
  yield api.step('echo', ['echo', 'Hello World'],
      stdout=api.raw_io.output(),
      stderr=api.raw_io.output())
  assert api.step_history.last_step().stdout == 'Hello World\n'
  assert api.step_history.last_step().stderr == ''

  # Pass stuff to command's stdin, read it from stdout.
  yield api.step('cat', ['cat'],
      stdin=api.raw_io.input(data='hello'),
      stdout=api.raw_io.output('out'))
  output = api.step_history.last_step().stdout
  assert output == 'hello'

  # Example of auto-mocking stdout
  yield api.step('automock', ['echo', output],
                 stdout=api.raw_io.output('out'),
                 step_test_data=(
                   lambda: api.raw_io.test_api.stream_output(output)))
  assert api.step_history.last_step().stdout == output

  # Example of auto-mocking stdout + stderr
  yield api.step(
    'automock (fail)', ['echo', output],
    stdout=api.raw_io.output('out'),
    stderr=api.raw_io.output('err'),
    step_test_data=(
      lambda: (
        api.raw_io.test_api.stream_output(output) +
        api.raw_io.test_api.stream_output('fail', 'stderr')
      ))
  )
  assert api.step_history.last_step().stdout == output
  assert api.step_history.last_step().stderr == 'fail'


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo',
          stdout=api.raw_io.output('Hello World\n'),
          stderr=api.raw_io.output('')) +
      api.step_data('cat',
          stdout=api.raw_io.output('hello')))
