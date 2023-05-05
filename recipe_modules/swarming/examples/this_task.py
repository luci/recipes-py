# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'step',
  'swarming',
]


def RunSteps(api):
  logs = api.step(cmd=None, name='task_info').presentation.logs
  logs['bot_id'] = [api.swarming.bot_id]
  logs['task_id'] = [api.swarming.task_id]
  logs['swarming_server'] = [api.swarming.current_server]


def GenTests(api):
  yield api.test('simulated') + api.swarming.properties()
