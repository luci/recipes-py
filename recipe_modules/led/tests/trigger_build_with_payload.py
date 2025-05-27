# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.go.chromium.org.luci.swarming.proto.api_v2 import swarming
from PB.recipe_modules.recipe_engine.led.properties import InputProperties

DEPS = [
    'led',
    'properties',
    'step',
]


def RunSteps(api):
  api.led.trigger_builder(
      'chromium',
      'ci',
      'Foo Tester', {'swarm_hashes': {
          'bar': 'deadbeef'
      }},
      use_payload=True)


def GenTests(api):
  led_run_id = 'led/user_example.com/deadbeef'
  yield api.test(
      'trigger',
      api.properties(
          **{
              '$recipe_engine/led':
                  InputProperties(
                      led_run_id=led_run_id,
                      rbe_cas_input=swarming.CASReference(
                          cas_instance='projects/example/'
                          'instances/default_instance',
                          digest=swarming.Digest(
                              hash='examplehash',
                              size_bytes=71,
                          ),
                      ))
          }))
