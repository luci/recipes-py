# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.recipe_modules.recipe_engine.led.properties import InputProperties

DEPS = [
  'led',
  'properties',
  'step',
]

def RunSteps(api):
  if api.led.launched_by_led:
    if api.properties.get('real_build'):
      api.led.trigger_builder(
          'chromium',
          'ci',
          'Foo Tester', {'swarm_hashes': {
              'bar': 'deadbeef'
          }},
          real_build=True)
    else:
      api.led.trigger_builder('chromium', 'ci', 'Foo Tester',
                              {'swarm_hashes': {
                                  'bar': 'deadbeef'
                              }})


def GenTests(api):
  led_run_id = 'led/user_example.com/deadbeef'
  yield api.test(
      'trigger',
      api.properties(
          **{'$recipe_engine/led': InputProperties(led_run_id=led_run_id)})
  )
  yield api.test(
      'trigger-real-build',
      api.properties(
          **{
              '$recipe_engine/led': InputProperties(led_run_id=led_run_id),
              'real_build': True
          }))
