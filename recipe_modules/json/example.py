# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'json',
  'path',
  'python',
  'raw_io',
  'step',
]

FULLWIDTH_Z = u'\ufeff\uff5a'

def RunSteps(api):
  step_result = api.step('echo1', ['echo', '[1, 2, 3]'],
      stdout=api.json.output())
  assert step_result.stdout == [1, 2, 3], step_result.stdout

  # Example demonstrating the usage of step_test_data for json stdout.
  step_result = api.step('echo2', ['echo', '[2, 3, 4]'],
      step_test_data=lambda: api.json.test_api.output_stream([2, 3, 4]),
      stdout=api.json.output())
  assert step_result.stdout == [2, 3, 4]

  assert api.json.is_serializable('foo')
  assert not api.json.is_serializable(set(['foo', 'bar', 'baz']))

  # Example demonstrating multiple named json output files.
  result = api.python.inline(
      'foo',
      """
      import json
      import sys
      with open(sys.argv[1], 'w') as f:
        f.write(json.dumps([1, 2, 3]))
      with open(sys.argv[2], 'w') as f:
        f.write(json.dumps(['x', 'y', %s]))
      """ % repr(FULLWIDTH_Z),
      args=[api.json.output(name='1'), api.json.output(name='2')],
  )
  assert result.json.outputs['1'] == [1, 2, 3]
  assert result.json.outputs['2'] == ['x', 'y', FULLWIDTH_Z]
  assert not hasattr(result.json, 'output')

  example_dict = {'x': 1, 'y': 2}

  # json.input(json_data) expands to a path containing that rendered json
  step_result = api.step('json through',
    ['cat', api.json.input(example_dict)],
    stdout=api.json.output(),
    step_test_data=lambda: api.json.test_api.output_stream(example_dict))
  assert step_result.stdout == example_dict

  # json.read reads a file containing json data.
  leak_path = api.path['slave_build'].join('temp.json')
  api.step('write json to file',
    ['cat', api.json.input(example_dict)],
    stdout=api.raw_io.output(leak_to=leak_path))
  step_result = api.json.read(
      'read json from file we just wrote', leak_path,
      step_test_data=lambda: api.json.test_api.output(example_dict))
  assert step_result.json.output == example_dict


def GenTests(api):
  yield (api.test('basic') +
      api.step_data('echo1', stdout=api.json.output([1, 2, 3])) +
      api.step_data(
          'foo',
          api.json.output([1, 2, 3], name='1') +
          api.json.output(['x', 'y', FULLWIDTH_Z], name='2'),
      ))
