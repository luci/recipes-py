# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'path',
  'properties',
  'python',
  'raw_io',
  'step',
]


def RunSteps(api):
  # Read command's stdout and stderr.
  step_result = api.step('echo', ['echo', 'Hello World'],
      stdout=api.raw_io.output(),
      stderr=api.raw_io.output())
  assert step_result.stdout == 'Hello World\n'
  assert step_result.stderr == ''

  # Pass stuff to command's stdin, read it from stdout.
  step_result = api.step('cat', ['cat'],
      stdin=api.raw_io.input_text(data='hello'),
      stdout=api.raw_io.output('out'))
  assert step_result.stdout == 'hello'

  step_result = api.step('cat', ['cat', api.raw_io.input_text(data='hello')],
      stdout=api.raw_io.output('out'))
  assert step_result.stdout == 'hello'

  # \xe2 is not encodable by utf-8 (and has shown up in actual recipe data)
  # so test that input correctly doesn't try to encode it as utf-8.
  step_result = api.step('cat', ['cat'],
      stdin=api.raw_io.input(data='\xe2hello'),
      stdout=api.raw_io.output())
  assert step_result.stdout == '\xe2hello'

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
      stdout=api.raw_io.output(leak_to=api.path['tmp_base'].join('out.txt')),
      step_test_data=(
        lambda: api.raw_io.test_api.stream_output('leaking\n')))
  assert step_result.stdout == 'leaking\n'

  api.step('list temp dir', ['ls', api.raw_io.output_dir()])
  api.step('leak dir', ['ls', api.raw_io.output_dir(
      leak_to=api.path['tmp_base'].join('out'))])

  # Example of overriding default mocked output for a single named output.
  step_result = api.python.inline(
      'override_default_mock',
      """
      import sys
      with open(sys.argv[1], 'w') as f:
        f.write(%r)
      """ % api.properties.get('some_prop', 'good_value'),
      args=[api.raw_io.output_text(name='test')],
      step_test_data=(
          lambda: api.raw_io.test_api.output_text(
              'second_bad_value', name='test')))
  assert step_result.raw_io.output_texts['test'] == 'good_value'
  assert step_result.raw_io.output_text == 'good_value'


def GenTests(api):
  # This test shows that you can override a specific placeholder, even with
  # default `step_test_data`. However, since this recipe is ACTUALLY run in
  # the presubmit, we need to do a trick with properties:
  #   When run for real, "some_prop" will be "good_value" and pass.
  #   When run for simulation, we override this property to provide a bad value,
  #     AND the default step_test_data in RunSteps above ALSO provides another
  #     bad value, the simulation passes ONLY because of the
  #     'override_default_mock' below.
  yield (api.test('basic') +
      api.properties(some_prop='bad_value') +
      api.step_data('echo',
          stdout=api.raw_io.output('Hello World\n'),
          stderr=api.raw_io.output('')) +
      api.step_data('cat',
          stdout=api.raw_io.output('hello')) +
      api.step_data('cat (2)',
          stdout=api.raw_io.output('hello')) +
      api.step_data('cat (3)',
          stdout=api.raw_io.output('\xe2hello')) +
      api.step_data('override_default_mock',
          api.raw_io.output_text('good_value', name='test'))
  )
