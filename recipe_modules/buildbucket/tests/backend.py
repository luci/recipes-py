# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import task as task_pb2


DEPS = [
    'assertions',
    'buildbucket',
]


def RunSteps(api):
  api.assertions.assertEqual(api.buildbucket.backend_hostname, 'foo')
  api.assertions.assertEqual(
    api.buildbucket.backend_task_dimensions[0],
    common_pb2.RequestedDimension(key="key", value="val"))
  api.assertions.assertEqual(api.buildbucket.backend_task_id, "1")
  api.assertions.assertEqual(
      api.buildbucket.backend_task_id_from_build(api.buildbucket.build), "1")
  api.assertions.assertEqual(
    api.buildbucket.swarming_bot_dimensions[0].key, "os")
  api.assertions.assertEqual(
    api.buildbucket.swarming_bot_dimensions[0].value, "mac")
  api.assertions.assertEqual(
    api.buildbucket.swarming_bot_dimensions_from_build(
      api.buildbucket.build)[0].key, "os")
  api.assertions.assertEqual(api.buildbucket.swarming_parent_run_id, "1")
  api.assertions.assertEqual(api.buildbucket.swarming_priority, 1)
  api.assertions.assertEqual(
    api.buildbucket.swarming_task_service_account, "abc123@email.com")


def GenTests(api):
  task_details_dict = {
      'bot_dimensions': {
          'os': ['mac'],
      },
  }
  task_details = api.buildbucket.dict_to_struct(task_details_dict)

  backend_config_dict = {
      'task_service_account': 'abc123@email.com',
      'parent_run_id': '1',
      'priority': 1,
  }
  backend_config = api.buildbucket.dict_to_struct(backend_config_dict)

  yield (
      api.test('swarming_as_a_backend') +
      api.buildbucket.backend_build(
          project='my-proj',
          builder='win',
          task=task_pb2.Task(
              id=task_pb2.TaskID(
                  id="1",
                  target="swarming://chromium-swarm"
              ),
              details=task_details
          ),
          backend_hostname="foo",
          task_dimensions=[
            common_pb2.RequestedDimension(key="key", value="val")
          ],
          backend_config=backend_config,
      ) + api.post_process(post_process.DropExpectation)
  )

  yield (
        api.test('raw_swarming') +
        api.buildbucket.raw_swarming_build(
            project='my-proj',
            builder='win',
            hostname="foo",
            task_dimensions=[
                common_pb2.RequestedDimension(key="key", value="val")
            ],
            task_id="1",
            parent_run_id="1",
            priority=1,
            task_service_account="abc123@email.com",
            bot_dimensions=[common_pb2.StringPair(key="os", value="mac")]
        ) + api.post_process(post_process.DropExpectation)
    )
