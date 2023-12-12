# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from recipe_engine.post_process import DropExpectation

DEPS = [
    'assertions',
    'swarming',
    'path',
]


def RunSteps(api):
  script_path = api.path.join(api.path.dirname(__file__))
  collect_path = api.path.join(script_path, "example_collect_output.json")
  request_path = api.path.join(script_path, "example_request_show_output.json")
  with open(collect_path) as collect_file, open(request_path) as request_file:
    collect_jsonish = json.load(collect_file)
    request_jsonish = json.load(request_file)
    # basic sanity check
    api.assertions.assertTrue(len(request_jsonish["task_slices"]) == 2)
    api.assertions.assertTrue(len(collect_jsonish) > 0)
    task_id = "656757b8221c3a10"
    request = api.swarming.task_request_from_jsonish(request_jsonish)
    result = api.swarming.TaskResult(api, request[0], task_id,
                                     collect_jsonish[task_id], None)
    api.assertions.assertEqual(task_id, result.id)
    api.assertions.assertEqual(result.state, api.swarming.TaskState.COMPLETED)
    api.assertions.assertTrue(result.finalized)
    api.assertions.assertEqual(result.name, request.name)
    api.assertions.assertEqual(result.bot_id,
                               "linux-bionic-local-ssd-dev-0-lppg")
    api.assertions.assertTrue(result.success)
    api.assertions.assertEqual(result.duration_secs, 104.25532)

    # test state finalization
    collect_jsonish[task_id]["results"]["state"] = "RUNNING"
    result = api.swarming.TaskResult(api, request[0], task_id,
                                     collect_jsonish[task_id], None)
    api.assertions.assertEqual(result.state, api.swarming.TaskState.RUNNING)
    api.assertions.assertFalse(result.finalized)
    api.assertions.assertFalse(result.output)
    api.assertions.assertFalse(result.duration_secs)
    api.assertions.assertFalse(result.success)


def GenTests(api):
  yield (api.test('aio') + api.post_process(DropExpectation))
