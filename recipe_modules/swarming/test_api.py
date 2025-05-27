# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


from __future__ import annotations

import json

from recipe_engine import recipe_test_api
from PB.recipe_modules.recipe_engine.swarming import properties

from .api import TaskRequest
from .state import TaskState


class SwarmingTestApi(recipe_test_api.RecipeTestApi):
  TaskState = TaskState

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._task_id_count = 0
    self._saved_task_for_show_request = None

  def check_triggered_request(self, check, step_odict, step, *checkers):
    """Check the input request of a swarming trigger call.

    Args:
      check, step_odict: provided by post_process
      step (str): the step name to check
      checkers (Seq[lambda]): a list of functions that take in two args: |check|
        and a TaskRequest object.

    Example usage:
      c1 = lambda check, req: check(req[0].dimensions == {'os': 'Linux'})
      c2 = lambda check, req: check(req[0].env == {'FOO': '42'})
      post_check(api.swarming.check_triggered_request, 'trigger foo', c1, c2)
    """
    # step.json.input is not available.
    cmd = step_odict[step].cmd
    json_d = cmd[cmd.index('-json-input') + 1]
    json_reqs = json.loads(json_d)['requests']
    for jr in json_reqs:
      req = TaskRequest(self.m)._from_jsonish(jr)
      for c in checkers:
        c(check, req)

  def example_task_request_jsonish(self):
    """Returns a dict that can be parsed by task_request_from_jsonish()."""
    return {
        'name': 'QEMU',
        'priority': 20,
        'service_account': 'foo@example.com',
        'task_slices': [{
            'expiration_secs': '18000',
            'properties': {
                'cipd_input': {
                    'packages': [],
                    'server': ''
                },
                'command': ['/bin/true'],
                'relative_cwd': 'some/dir',
                'containment': {
                    'containment_type': 'NONE',
                    'limit_processes': False,
                    'limit_total_committed_memory': False,
                    'lower_priority': False,
                },
                'dimensions': [{
                    'key': 'pool',
                    'value': 'swarming-pool',
                }],
                'env': [],
                'env_prefixes': [],
                'execution_timeout_secs': '2400',
                'grace_period_secs': '30',
                'cas_input_root': {
                    'cas_instance':
                        'projects/example-project/instances/default_instance',
                    'digest': {
                        'hash':
                            '24b2420bc49d8b8fdc1d011a163708927532b37dc9f91d7d8d6877e3a86559ca',
                        'size_bytes':
                            '73',
                    },
                },
                'idempotent': False,
                'io_timeout_secs': '430',
                'outputs': []
            }
        }],
        'realm': 'project:bucket',
        'resultdb': {
            'enable': True,
        },
    }

  def properties(self, task_id='fake-task-id', bot_id='fake-bot-id'):
    return self.m.properties.environ(
        properties.EnvProperties(
            SWARMING_TASK_ID=task_id, SWARMING_BOT_ID=bot_id))

  def trigger(self, task_names, initial_id=None, resultdb=True):
    """Generates step test data intended to mock api.swarming.trigger()

    Args:
      task_names (seq[str]): A sequence of task names representing the tasks we
        want to trigger.
      initial_id (int): The beginning of the ID range.
      resultdb (bool|seq[bool]): If true, adds an invocation name to the trigger
        output. A sequence of bools can be passed to add an invocation on a
        task-by-task basis.
    """
    start = self._task_id_count if initial_id is None else initial_id
    self._task_id_count += len(task_names)
    if resultdb in (True, False):
      resultdb = [resultdb] * len(task_names)
    assert len(resultdb) == len(task_names)
    trigger_output = {'tasks': []}
    for idx, (name, add_invocation) in enumerate(
        zip(task_names, resultdb), start=start):
      task_output = {
        'task_id': '%d' % idx,
        'request': {
          'name': name,
        },
      }
      if add_invocation:
        task_output['task_result'] = {
          'resultdb_info': {
            'invocation': 'invocations/%d' % idx,
          },
        }

      trigger_output['tasks'].append(task_output)
    return self.m.json.output(trigger_output)

  @staticmethod
  def task_result(id,
                  name,
                  state=TaskState.COMPLETED,
                  duration=62.35,
                  failure=False,
                  output='hello world!',
                  outputs=(),
                  bot_id='vm-123'):
    """
    Returns the raw results of a Swarming task.

    Args:
      id (str): The ID of the task.
      name (str): The name of the task.
      state (TaskState|None): The final state of the task; if None, the task is
        regarded to be in an unknown state.
      duration (int): The duration of the task
      failure (bool): Whether the task failed; ignored if state is not
        TaskState.COMPLETE.
      output (str): That raw output of the task.
      outputs (seq(str)):
    """
    assert isinstance(state, TaskState) or state == None
    assert state not in [
        TaskState.INVALID,
        TaskState.PENDING,
        TaskState.RUNNING,
    ], 'state %s invalid or not final' % state.name
    if state == None:
      return {
          'error': 'Bot could not be contacted',
          'results': {
              'task_id': id
          },
      }
    cas_hash = '24b2420bc49d8b8fdc1d011a163708927532b37dc9f91d7d8d6877e3a86559ca'
    raw_results = {
        'output': output,
        'outputs': outputs,
        'results': {
            'bot_id': bot_id,
            'name': name,
            'task_id': id,
            'state': state.name,
            'duration': duration,
            'created_ts': '2025-04-23T19:10:21.951949Z',
            'started_ts': '2025-04-23T19:13:55.431522Z',
            'completed_ts': '2025-04-23T20:01:13.072079Z',
            'cas_output_root': {
                'cas_instance':
                    'projects/example-project/instances/default_instance',
                'digest': {
                    'hash': cas_hash,
                    'size_bytes': '73',
                },
            },
            'resultdb_info': {
                'invocation': 'invocations/some-inv-name',
            },
        },
    }

    if state == TaskState.COMPLETED:
      raw_results['results']['exit_code'] = str(int(failure))

    return raw_results

  def collect(self, task_results):
    """Generates test step data for the swarming API collect method.

    Args:
      task_results (seq[dict]): A sequence of dicts encoding swarming task
        results.

    Returns:
      Step test data in the form of JSON output intended to mock a swarming API
      collect method call.
    """
    id_to_result = {
        result['results']['task_id']: result for result in task_results
    }
    return self.m.json.output(id_to_result)

  def set_task_for_show_request(self, task):
    self._saved_task_for_show_request = task

  def show_request(self):
    """Return saved TaskRequest jsonish data for the Swarming API show-request
    method.

    Returns:
      Step test data in the form of JSON output intended to mock a swarming API
      show-request method call.
    """
    task = self._saved_task_for_show_request
    if isinstance(task, TaskRequest):
      task = task.to_jsonish()
    return self.m.json.output_stream(task)

  def generate_bot_json(self,
                        bot_id,
                        is_dead=False,
                        quarantined=False,
                        maintenance_msg=None,
                        dimensions=None,
                        state=None):
    bot = {'bot_id': bot_id}
    if is_dead:
      bot['is_dead'] = True
    if quarantined:
      bot['quarantined'] = True
    if maintenance_msg:
      bot['maintenance_msg'] = maintenance_msg
    if dimensions:
      bot['dimensions'] = [{
          'key': k,
          'value': v
      } for k, v in dimensions.items()]
    if state:
      bot['state'] = self.m.json.dumps(state)
    return bot

  def list_bots(self, dimensions=None):
    """Generates step test data intended to mock api.swarming.list_bots()

    Args:
      dimensions (None|Dict[str, str]): Select bots that match the given
        dimensions.
    """
    raw_results = [
        self.generate_bot_json(
            'build11-dead--device1',
            is_dead=True,
            dimensions=dimensions),
        self.generate_bot_json(
            'build12-quarantined--device1',
            quarantined=True,
            dimensions=dimensions),
        self.generate_bot_json(
            'build13-maintenance--device1',
            maintenance_msg='In maintenance mode',
            dimensions=dimensions),
        self.generate_bot_json(
            'build14-alive--device1',
            dimensions=dimensions,
            state={'devices': {
                'build13-alive-1-serial': {
                    'max_uid': 19999,
                }
            }}),
    ]
    return self.m.json.output(raw_results)
