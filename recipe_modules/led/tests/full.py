# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'buildbucket',
  'led',
  'json',
  'properties',
  'step',
]

from recipe_engine.recipe_api import Property
from PB.recipe_modules.recipe_engine.led.properties import InputProperties

PROPERTIES = {
  'child_properties': Property(default=None, kind=dict),
}


def RunSteps(api, child_properties):
  intermediate = api.led(
      'get-builder', 'luci.chromium.try:linux_chromium_rel_ng')
  intermediate = intermediate.then('edit-cr-cl', 'https://fake.url/123')

  # Only use a different version of the recipes code if this is a led job.
  if api.led.launched_by_led:
    assert api.led.run_id
    intermediate = api.led.inject_input_recipes(intermediate)

  if child_properties:
    edit_args = ['edit']
    for k, v in child_properties.items():
      edit_args.extend(['-p', '%s=%s' % (k, v)])
    intermediate = intermediate.then(*edit_args)

  final_result = intermediate.then('launch')
  api.step('print task id', [
      'echo', final_result.result['swarming']['task_id']])


def GenTests(api):
  def led_props(input_properties):
    return api.properties(**{'$recipe_engine/led': input_properties})

  yield (
      api.test('basic') +
      api.led.get_builder(api).launch().step_data
  )

  isolated_hash = 'somehash123'
  led_run_id = 'led/user_example.com/deadbeef'
  yield (
      api.test('with-isolated-input') +
      led_props(InputProperties(
          led_run_id=led_run_id,
          isolated_input=InputProperties.IsolatedInput(
              hash=isolated_hash,
              namespace='default-gzip',
              server='isolateserver.appspot.com',
          ),
      )) +
      api.led.get_builder(api)
             .edit_input_recipes(isolated_hash=isolated_hash)
             .launch()
             .step_data
  )

  cipd_source = {
      'package': 'recipe_dir/recipes',
      'version': 'refs/heads/master',
  }
  yield (
      api.test('with-cipd-input') +
      led_props(InputProperties(
          led_run_id=led_run_id,
          cipd_input=InputProperties.CIPDInput(**cipd_source),
      )) +
      api.led.get_builder(api)
             .edit_input_recipes(cipd_source=cipd_source)
             .launch()
             .step_data
  )

  child_properties = {'prop': 'val'}
  yield (
      api.test('edit-properties') +
      api.properties(child_properties=child_properties) +
      led_props(InputProperties(led_run_id=led_run_id)) +
      api.led.get_builder(api)
             .edit_properties(**child_properties)
             .launch()
             .step_data
  )
