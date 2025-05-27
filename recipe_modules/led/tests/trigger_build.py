# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipe_modules.recipe_engine.led.properties import InputProperties

DEPS = [
  'led',
  'properties',
  'step',
]

def RunSteps(api):
  api.led.trigger_builder('chromium', 'ci', 'Foo Tester',
                          {'swarm_hashes': {
                              'bar': 'deadbeef'
                          }})


def GenTests(api):
  led_run_id = 'led/user_example.com/deadbeef'
  yield api.test(
      'trigger',
      api.properties(
          **{'$recipe_engine/led': InputProperties(led_run_id=led_run_id)}))
