# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'assertions',
    'swarming',
    'time',
]


def RunSteps(api):
  tasks = api.swarming.list_tasks(
      'List Tasks', tags=['foo:bar'], start=api.time.time())
  api.assertions.assertEqual(len(tasks), 1)
  api.assertions.assertEqual(tasks[0]['tags'], ['foo:bar'])


def GenTests(api):
  yield api.test(
      'basic',
      api.time.seed(12341234),
      api.post_process(post_process.StepCommandContains, 'List Tasks',
                       ['-tag', 'foo:bar']),
      api.post_process(post_process.StepCommandContains, 'List Tasks',
                       ['-start', '12341235.5']),
      api.post_process(post_process.DropExpectation),
  )
