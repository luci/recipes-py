# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'assertions',
    'swarming',
]


def RunSteps(api):
  # TaskRequset._from_jsonish should accept empty dict, that all fields are
  # omitted.
  task = api.swarming.task_request_from_jsonish({})
  api.assertions.assertEqual(len(task), 0)

  # TaskSlice._from_jsonish should accept empty dict.
  task = api.swarming.task_request_from_jsonish({'task_slices': [{}]})
  api.assertions.assertEqual(len(task), 1)

  # TaskSlice._from_jsonish should accept empty task properties.
  task = api.swarming.task_request_from_jsonish(
      {'task_slices': [{
          'properties': {}
      }]})
  api.assertions.assertEqual(len(task), 1)

  # cas_input_root.digest.size_bytes could be 0
  task = api.swarming.task_request_from_jsonish({
      'task_slices': [{
          'properties': {
              'cas_input_root': {
                  'digest': {
                      'hash':
                          'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
                  }
              }
          }
      }]
  })
  api.assertions.assertEqual(len(task), 1)


def GenTests(api):
  yield (api.test('aio') + api.post_process(DropExpectation))
