# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'json',
  'step',
]


def RunSteps(api):
  step_result = api.step('echo1', ['echo', '[1, 2, 3]'],
      stdout=api.json.output())
  assert step_result.stdout == [1, 2, 3]

  # Example demonstrating the usage of step_test_data for json stdout.
  step_result = api.step('echo2', ['echo', '[2, 3, 4]'],
      step_test_data=lambda: api.json.test_api.output_stream([2, 3, 4]),
      stdout=api.json.output())
  assert step_result.stdout == [2, 3, 4]

  assert api.json.is_serializable('foo')
  assert not api.json.is_serializable(set(['foo', 'bar', 'baz']))


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo1', stdout=api.json.output([1, 2, 3])))
