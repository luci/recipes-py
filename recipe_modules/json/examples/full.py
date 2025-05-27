# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'json',
  'path',
  'properties',
  'raw_io',
  'step',
]

import textwrap

from google.protobuf import struct_pb2

from recipe_engine import engine_types, recipe_api

FULLWIDTH_Z = u'\ufeff\uff5a'

@recipe_api.ignore_warnings('recipe_engine/JSON_READ_DEPRECATED')
def RunSteps(api):
  step_result = api.step('echo1', ['echo', '[1, 2, 3]'],
      stdout=api.json.output())
  assert step_result.stdout == [1, 2, 3], step_result.stdout

  # have to provide a default value for example_dumps because the
  # 'example_tests' unittest runs all these example recipes without any input
  # properties.
  api.step('echo_dumps_property', [
    'echo', api.properties.get('example_dumps', '[100]')])

  # Example demonstrating the usage of step_test_data for JSON stdout.
  step_result = api.step('echo2', ['echo', '[2, 3, 4]'],
      step_test_data=lambda: api.json.test_api.output_stream([2, 3, 4]),
      stdout=api.json.output())
  assert step_result.stdout == [2, 3, 4]

  assert api.json.is_serializable('foo')
  assert not api.json.is_serializable(set(['foo', 'bar', 'baz']))

  # Example demonstrating multiple named JSON output files.
  program = textwrap.dedent("""
  import json
  import sys
  with open(sys.argv[1], 'w') as f:
    f.write(json.dumps([1, 2, 3]))
  with open(sys.argv[2], 'w') as f:
    f.write(json.dumps(['x', 'y', u'%s']))
  """ % (FULLWIDTH_Z,))

  result = api.step('foo', [
      'python3',
      api.raw_io.input_text(program, suffix='.py'),
      api.json.output(name='1'),
      api.json.output(name='2'),
  ])
  assert result.json.outputs['1'] == [1, 2, 3]
  assert result.json.outputs['2'] == ['x', 'y', FULLWIDTH_Z]
  assert not hasattr(result.json, 'output')

  example_dict = {'x': 1, 'y': 2}

  # json.input(json_data) expands to a path containing that rendered JSON.
  step_result = api.step('json through',
    ['cat', api.json.input(example_dict)],
    stdout=api.json.output(),
    step_test_data=lambda: api.json.test_api.output_stream(example_dict))
  assert step_result.stdout == example_dict

  # json.read reads a file containing JSON data.
  leak_path = api.path.tmp_base_dir / 'temp.json'
  api.step('write json to file',
    ['cat', api.json.input(example_dict)],
    stdout=api.raw_io.output(leak_to=leak_path))
  step_result = api.json.read(
      'read json from file we just wrote', leak_path,
      step_test_data=lambda: api.json.test_api.output(example_dict))
  assert step_result.json.output == example_dict

  # Can leak directly to a file.
  step_result = api.step('leaking json', [
      'python3',
      api.resource('cool_script.py'),
      '{"x":1,"y":2}',
      api.json.output(leak_to=api.path.tmp_base_dir / 'leak.json'),
  ])
  assert step_result.json.output == example_dict

  # Invalid data gets rendered.
  step_result = api.step('invalid json', [
      'python3',
      api.resource('cool_script.py'),
      '{"here is some total\ngarbage',
      api.json.output(),
  ])
  assert step_result.json.output is None

  step_result = api.step(
    'backing file missing',
    [
      'python3', api.resource('cool_script.py'),
      'file missing',
      api.json.output(leak_to='/this/file/doesnt/exist'),
    ],
    ok_ret=(1,))
  assert step_result.json.output is None

  # Check that certain non-stdlib types are JSON serializable.
  assert api.json.dumps(api.path.start_dir) == '"%s"' % api.path.start_dir
  assert api.json.dumps(engine_types.FrozenDict(foo='bar')) == '{"foo": "bar"}'
  foobar_struct = struct_pb2.Struct(
      fields={'foo': struct_pb2.Value(string_value='bar')})
  assert api.json.dumps(foobar_struct) == '{"foo": "bar"}'


def GenTests(api):
  yield (
    api.test('basic')
    + api.properties(
      example_dumps=api.json.dumps({
        'hello': 'world',
        'cool': [1, 2, 3],
      })
    )
    + api.step_data('echo1', stdout=api.json.output([1, 2, 3]))
    + api.step_data(
      'foo',
      api.json.output([1, 2, 3], name='1') +
      api.json.output(['x', 'y', FULLWIDTH_Z], name='2'),
    )
    + api.step_data(
      'leaking json',
      api.json.output({'x': 1, 'y': 2}),
    )
    + api.step_data(
      'invalid json',
      api.json.invalid('{"here is some total\ngarbage'),
    )
    + api.step_data(
      'backing file missing',
      api.json.backing_file_missing(),
      retcode=1,
    )
  )
