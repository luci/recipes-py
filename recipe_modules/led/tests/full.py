# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'led',
  'json',
  'properties',
  'step',
]

from PB.recipe_modules.recipe_engine.led.properties import InputProperties


def RunSteps(api):
  intermediate = api.led(
      'get-builder', 'luci.chromium.try:linux_chromium_rel_ng')
  intermediate = intermediate.then('edit-cr-cl', 'https://fake.url/123')
  # Only use a different version of the recipes code if this is a led job.
  if api.led.launched_by_led:
    intermediate = api.led.inject_input_recipes(intermediate)
  final_result = intermediate.then('launch')
  api.step('print task id', [
      'echo', final_result.result['swarming']['task_id']])


def GenTests(api):
  def mock_led(cmd, output_json):
    return api.step_data('led %s' % cmd, stdout=api.json.output(output_json))

  def props(input_properties):
    return api.properties(**{'$recipe_engine/led': input_properties})

  def mock_led_launch(output_json=None):
    if output_json is None:
      output_json = {
          'swarming': {
              'host_name': 'chromium-swarm.appspot.com',
              'task_id': 'deadbeeeeef',
          }
      }
    return mock_led('launch', output_json)

  def mock_led_get_builder(output_json=None):
    if output_json is None:
      output_json = {'task_data': 'foo'}
    return mock_led('get-builder', output_json)

  yield api.test('basic') + mock_led_get_builder() + mock_led_launch()

  isolated_hash = 'somehash123'
  yield (
      api.test('with-isolated-input') +
      props(InputProperties(
          launched_by_led=True,
          isolated_input=InputProperties.IsolatedInput(
              hash=isolated_hash,
              namespace='default-gzip',
              server='isolateserver.appspot.com',
          ),
      )) +
      mock_led_get_builder() +
      mock_led('edit', {
          'task_data': 'foo',
          'recipe_isolated_hash': isolated_hash,
      }) +
      mock_led_launch()
  )

  cipd_package = 'recipe_dir/recipes'
  cipd_version = 'refs/heads/master'
  yield (
      api.test('with-cipd-input') +
      props(InputProperties(
          launched_by_led=True,
          cipd_input=InputProperties.CIPDInput(
              package=cipd_package,
              version=cipd_version,
          ),
      )) +
      mock_led_get_builder() +
      mock_led('edit', {
          'task_data': 'foo',
          'recipe_cipd_source': {
              'cipd_package': cipd_package,
              'cipd_version': cipd_version,
          }
      }) +
      mock_led_launch()
  )

  yield (
      api.test('no-input-recipes') +
      props(InputProperties(launched_by_led=True)) +
      mock_led_get_builder() +
      mock_led_launch()
  )
