# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import task as task_pb2


DEPS = ['assertions', 'buildbucket', 'properties', 'step']


def RunSteps(api):
  api.assertions.assertEqual(api.buildbucket.backend_hostname, 'foo')
  api.assertions.assertEqual(
    api.buildbucket.backend_task_dimensions[0],
    common_pb2.RequestedDimension(key="key", value="val"))
  api.assertions.assertEqual(api.buildbucket.backend_task_id, "1")
  api.assertions.assertEqual(
      api.buildbucket.backend_task_id_from_build(api.buildbucket.build), "1")
  bot_dims = api.buildbucket.swarming_bot_dimensions
  api.assertions.assertEqual(bot_dims[0].key, "os")
  api.assertions.assertEqual(bot_dims[0].value, "mac")
  api.assertions.assertEqual(bot_dims[1].key, "key1")
  api.assertions.assertEqual(bot_dims[1].value, "value1")
  api.assertions.assertEqual(bot_dims[2].key, "key2")
  api.assertions.assertEqual(bot_dims[2].value, "value2")
  api.assertions.assertEqual(bot_dims[3].key, "key2")
  api.assertions.assertEqual(bot_dims[3].value, "value3")
  api.assertions.assertEqual(
      api.buildbucket.swarming_bot_dimensions_from_build(
          api.buildbucket.build)[0].key, "os")

  if api.properties.get('update_backend_config'):
    api.assertions.assertEqual(api.buildbucket.swarming_parent_run_id, "new")
    api.assertions.assertEqual(api.buildbucket.swarming_priority, 30)
    api.assertions.assertEqual(
    api.buildbucket.swarming_task_service_account, "other@email.com")
  elif api.properties.get('update_swarming_config'):
    api.assertions.assertEqual(api.buildbucket.swarming_parent_run_id,
                               "new_for_swarming")
    api.assertions.assertEqual(api.buildbucket.swarming_priority, 50)
    api.assertions.assertEqual(api.buildbucket.swarming_task_service_account,
                               "other_sw@email.com")
  else:
    api.assertions.assertEqual(api.buildbucket.swarming_parent_run_id, "1")
    api.assertions.assertEqual(api.buildbucket.swarming_priority, 1)
    api.assertions.assertEqual(api.buildbucket.swarming_task_service_account,
                               "abc123@email.com")


def GenTests(api):

  def _setup_backend_build(update_backend_config=False,
                           use_default_bot_dims=True,
                           bot_dims={}):
    task_details_dict = {}
    if use_default_bot_dims:
      task_details_dict = {
          'bot_dimensions': {
              'os': ['mac'],
          },
      }
    task_details = api.buildbucket.dict_to_struct(task_details_dict)

    backend_config_dict = {
        'service_account': 'abc123@email.com',
        'parent_run_id': '1',
        'priority': 1,
    }
    backend_config = api.buildbucket.dict_to_struct(backend_config_dict)
    b = api.buildbucket.backend_build(
        project='my-proj',
        builder='win',
        task=task_pb2.Task(
            id=task_pb2.TaskID(id="1", target="swarming://chromium-swarm"),
            details=task_details),
        backend_hostname="foo",
        task_dimensions=[common_pb2.RequestedDimension(key="key", value="val")],
        backend_config=backend_config,
    )
    # Purely just to test that extend_swarming_bot_dimensions works.
    b = api.buildbucket.extend_swarming_bot_dimensions(b, bot_dims)

    if update_backend_config:
      b = api.buildbucket.update_backend_priority(build=b, priority=30)
      b = api.buildbucket.update_backend_parent_run_id(
          build=b, parent_run_id='new')
      b = api.buildbucket.update_backend_service_account(
          build=b, service_account='other@email.com')

    return api.buildbucket.build(b)

  def _setup_raw_swarming_build(update_swarming_config=False):
    b = api.buildbucket.raw_swarming_build(
        project='my-proj',
        builder='win',
        hostname="foo",
        task_dimensions=[common_pb2.RequestedDimension(key="key", value="val")],
        task_id="1",
        parent_run_id="1",
        priority=1,
        task_service_account="abc123@email.com",
        bot_dimensions=[
            common_pb2.StringPair(key="os", value="mac"),
        ])
    # Purely just to test that extend_swarming_bot_dimensions works for
    # raw swarming builds.
    b = api.buildbucket.extend_swarming_bot_dimensions(b, {
        "key1": "value1",
        "key2": ["value2", "value3"]
    })
    if update_swarming_config:
      b = api.buildbucket.update_backend_priority(build=b, priority=50)
      b = api.buildbucket.update_backend_parent_run_id(
          build=b, parent_run_id='new_for_swarming')
      b = api.buildbucket.update_backend_service_account(
          build=b, service_account='other_sw@email.com')
    return api.buildbucket.build(b)

  yield (api.test('swarming_as_a_backend') + _setup_backend_build(bot_dims={
      "key1": "value1",
      "key2": ["value2", "value3"]
  }) + api.post_process(post_process.DropExpectation))

  yield (api.test('swarming_as_a_backend_no_default_bot_dims') +
         _setup_backend_build(
             use_default_bot_dims=False,
             bot_dims={
                 "os": "mac",
                 "key1": "value1",
                 "key2": ["value2", "value3"]
             }) + api.post_process(post_process.DropExpectation))

  yield (api.test('update_backend_config') + _setup_backend_build(
      update_backend_config=True,
      bot_dims={
          "key1": "value1",
          "key2": ["value2", "value3"]
      }) + api.properties(update_backend_config=True) +
         api.post_process(post_process.DropExpectation))

  yield (api.test('raw_swarming') + _setup_raw_swarming_build() +
         api.post_process(post_process.DropExpectation))

  yield (api.test('raw_swarming_update_backend_config') +
         _setup_raw_swarming_build(update_swarming_config=True) +
         api.properties(update_swarming_config=True) +
         api.post_process(post_process.DropExpectation))

  # This is just to satisfy the test_api code coverage of 100%.
  yield (api.test('raw_swarming_build_message') +
         api.buildbucket.raw_swarming_build_message(
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
             bot_dimensions=[
                 common_pb2.StringPair(key="os", value="mac"),
                 common_pb2.StringPair(key="key1", value="value1"),
                 common_pb2.StringPair(key="key2", value="value2"),
                 common_pb2.StringPair(key="key2", value="value3"),
             ]) + api.post_process(post_process.DropExpectation))
