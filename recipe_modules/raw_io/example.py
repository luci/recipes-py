# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'path',
  'raw_io',
  'step',
]


def GenSteps(api):
  # Read command's stdout and stderr.
  step_result = api.step('echo', ['echo', 'Hello World'],
      stdout=api.raw_io.output(),
      stderr=api.raw_io.output())
  assert step_result.stdout == 'Hello World\n'
  assert step_result.stderr == ''

  # Pass stuff to command's stdin, read it from stdout.
  step_result = api.step('cat', ['cat'],
      stdin=api.raw_io.input(data='hello'),
      stdout=api.raw_io.output('out'))
  assert step_result.stdout == 'hello'

  # Example of auto-mocking stdout. '\n' appended to mock 'echo' behavior.
  step_result = api.step('automock', ['echo', 'huh'],
                 stdout=api.raw_io.output('out'),
                 step_test_data=(
                   lambda: api.raw_io.test_api.stream_output('huh\n')))
  assert step_result.stdout == 'huh\n'

  # Example of auto-mocking stdout + stderr.
  step_result = api.step(
    'automock (fail)', ['bash', '-c', 'echo blah && echo fail 1>&2'],
    stdout=api.raw_io.output('out'),
    stderr=api.raw_io.output('err'),
    step_test_data=(
      lambda: (
        api.raw_io.test_api.stream_output('blah\n') +
        api.raw_io.test_api.stream_output('fail\n', 'stderr')
      ))
  )
  assert step_result.stdout == 'blah\n'
  assert step_result.stderr == 'fail\n'

  # leak_to coverage.
  step_result = api.step(
      'leak stdout', ['echo', 'leaking'],
      stdout=api.raw_io.output(leak_to=api.path['slave_build'].join('out.txt')),
      step_test_data=(
        lambda: api.raw_io.test_api.stream_output('leaking\n')))
  assert step_result.stdout == 'leaking\n'


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo',
          stdout=api.raw_io.output('Hello World\n'),
          stderr=api.raw_io.output('')) +
      api.step_data('cat',
          stdout=api.raw_io.output('hello')))
