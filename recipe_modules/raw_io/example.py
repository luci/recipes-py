# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'path',
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
  assert api.step_history.last_step().stdout == 'hello'

  # Example of auto-mocking stdout. '\n' appended to mock 'echo' behavior.
  yield api.step('automock', ['echo', 'huh'],
                 stdout=api.raw_io.output('out'),
                 step_test_data=(
                   lambda: api.raw_io.test_api.stream_output('huh\n')))
  assert api.step_history.last_step().stdout == 'huh\n'

  # Example of auto-mocking stdout + stderr.
  yield api.step(
    'automock (fail)', ['bash', '-c', 'echo blah && echo fail 1>&2'],
    stdout=api.raw_io.output('out'),
    stderr=api.raw_io.output('err'),
    step_test_data=(
      lambda: (
        api.raw_io.test_api.stream_output('blah\n') +
        api.raw_io.test_api.stream_output('fail\n', 'stderr')
      ))
  )
  assert api.step_history.last_step().stdout == 'blah\n'
  assert api.step_history.last_step().stderr == 'fail\n'

  # leak_to coverage.
  yield api.step(
      'leak stdout', ['echo', 'leaking'],
      stdout=api.raw_io.output(leak_to=api.path['slave_build'].join('out.txt')),
      step_test_data=(
        lambda: api.raw_io.test_api.stream_output('leaking\n')))
  assert api.step_history.last_step().stdout == 'leaking\n'


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo',
          stdout=api.raw_io.output('Hello World\n'),
          stderr=api.raw_io.output('')) +
      api.step_data('cat',
          stdout=api.raw_io.output('hello')))
