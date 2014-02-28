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
  assert api.step_history.last_step().stdout == 'hello'


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo',
          stdout=api.raw_io.output('Hello World\n'),
          stderr=api.raw_io.output('')) +
      api.step_data('cat',
          stdout=api.raw_io.output('hello')))
