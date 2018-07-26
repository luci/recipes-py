# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'led',
  'json',
  'step',
]


def RunSteps(api):
  intermediate = api.led(
      'get-builder', 'luci.chromium.try:linux_chromium_rel_ng')
  intermediate = intermediate.then('edit-cr-cl', 'https://fake.url/123')
  final_result = intermediate.then('launch')
  api.step('print task id', [
      'echo', final_result.result['swarming']['task_id']])


def GenTests(api):
  yield (
      api.test('basic') +
      api.step_data('led get-builder',
                    stdout=api.json.output({
                        'task_data': 'foo',
                    })) +
      api.step_data('led launch',
                    stdout=api.json.output({
                      'swarming':{
                          'host_name': 'chromium-swarm.appspot.com',
                          'task_id': 'deadbeeeeef',
                      }
                    }))
  )
