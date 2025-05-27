# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from google.protobuf import struct_pb2

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import task as task_pb2


DEPS = [
    'assertions',
    'buildbucket',
]


def RunSteps(api):
  api.assertions.assertEqual(api.buildbucket.swarming_bot_dimensions, None)
  api.assertions.assertEqual(api.buildbucket.swarming_parent_run_id, None)
  api.assertions.assertEqual(api.buildbucket.swarming_priority, None)
  api.assertions.assertEqual(
    api.buildbucket.swarming_task_service_account, None)


def GenTests(api):
  task_details = struct_pb2.Struct(
      fields={
          "bot_dimensions": struct_pb2.Value(
              struct_value=struct_pb2.Struct(
                  fields={
                      "os": struct_pb2.Value(
                          list_value=struct_pb2.ListValue(
                              values=[
                                  struct_pb2.Value(string_value="mac")
                              ]
                          )
                      )
                  }
              )
          ),
        "parent_run_id": struct_pb2.Value(
          string_value="1"
        ),
        "priority": struct_pb2.Value(
          number_value=1
        ),
      }
  )
  backend_config = struct_pb2.Struct(
      fields={
          "task_service_account": struct_pb2.Value(
            string_value="abc123@email.com"
          )
      }
  )
  bad_backend_config = struct_pb2.Struct(
      fields={
          "taskk_service_account": struct_pb2.Value(
            string_value="abc123@email.com"
          )
      }
  )
  yield (api.test('non_swarming_backend') +
         api.buildbucket.backend_build_message(
             project='my-proj',
             builder='win',
             task=task_pb2.Task(
                 id=task_pb2.TaskID(
                     id="1", target="cloudbuild://chromium-cloudbuild"),
                 details=task_details),
             backend_hostname="foo",
             task_dimensions=[
                 common_pb2.RequestedDimension(key="key", value="val")
             ],
             backend_config=backend_config,
         ) + api.post_process(post_process.DropExpectation))
  yield (api.test('swarming_backend_no_config_or_task_details') +
         api.buildbucket.backend_build_message(
             project='my-proj',
             builder='win',
             task=task_pb2.Task(
                 id=task_pb2.TaskID(id="1", target="swarming://chromium-swarm"),
                 details=struct_pb2.Struct(fields={
                     "myfield": struct_pb2.Value(number_value=1),
                 })),
             backend_hostname="foo",
             task_dimensions=[
                 common_pb2.RequestedDimension(key="key", value="val")
             ],
         ) + api.post_process(post_process.DropExpectation))
  yield (api.test('swarming_backend_bad_config_no_task_details') +
         api.buildbucket.backend_build_message(
             project='my-proj',
             builder='win',
             task=task_pb2.Task(
                 id=task_pb2.TaskID(id="1", target="swarming://chromium-swarm"),
                 details=struct_pb2.Struct(fields={
                     "myfield": struct_pb2.Value(number_value=1),
                 })),
             backend_hostname="foo",
             task_dimensions=[
                 common_pb2.RequestedDimension(key="key", value="val")
             ],
             backend_config=bad_backend_config,
         ) + api.post_process(post_process.DropExpectation))
