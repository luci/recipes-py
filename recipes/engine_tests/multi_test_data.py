# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'raw_io',
  'step',
]

def RunSteps(api):
  doge = api.step('doge',
      ['doge'], stdout=api.raw_io.output(), stderr=api.raw_io.output())
  assert doge.stdout == b'such stdout'
  assert doge.stderr == b'so stderring'

def GenTests(api):
  yield (
    api.test('basic') +
    api.step_data('doge',
      api.raw_io.stream_output('such stdout', stream='stdout'),
      api.raw_io.stream_output('so stderring', stream='stderr')))
