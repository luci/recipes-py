# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'json',
  'step',
]

def RunSteps(api):
  example_dict = {'x': 1, 'y': 2}

  # not add a log for success
  step_result = api.step('no log on success',
    ['cat', '{"x":1,"y":2}'],
    stdout=api.json.output(add_json_log='on_failure', name='log1'),
  )
  assert step_result.stdout == example_dict
  assert 'json.output[log1]' not in step_result.presentation.logs

  # add a log for failure
  try:
    api.step('add log on failure',
      ['cat', '{"x":1,"y":2}'],
      stdout=api.json.output(add_json_log='on_failure', name='log2'),
    )
  except api.step.StepFailure:
    pass # This step is expected to fail.
  finally:
    step_result = api.step.active_result
    assert step_result.stdout == example_dict
    assert 'json.output[log2]' in step_result.presentation.logs
    actual_log_dict = api.json.loads(
        '\n'.join(step_result.presentation.logs['json.output[log2]']))
    assert actual_log_dict == example_dict


def GenTests(api):
  yield (
    api.test('add_json_log')
    + api.step_data(
      'no log on success',
      stdout=api.json.output({'x': 1, 'y': 2}, name='log1'),
    )
    + api.step_data(
      'add log on failure',
      stdout=api.json.output({'x': 1, 'y': 2}, name='log2'),
      retcode=1,
    )
  )
