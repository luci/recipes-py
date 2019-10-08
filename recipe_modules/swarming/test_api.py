# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from state import TaskState

from recipe_engine import recipe_test_api
from PB.recipe_modules.recipe_engine.swarming import properties


class SwarmingTestApi(recipe_test_api.RecipeTestApi):
  TaskState = TaskState

  def properties(self,
                 server='https://example.swarmingserver.appspot.com',
                 version='test_version',
                 task_id='fake-task-id',
                 bot_id='fake-bot'):
    return self.m.properties(**{
      '$recipe_engine/swarming': properties.InputProperties(
        server=server,
        version=version,
      ),
    }) + self.m.properties.environ(
      properties.EnvProperties(
        SWARMING_TASK_ID=task_id,
        SWARMING_BOT_ID=bot_id,
      )
    )

  def trigger(self, task_names, initial_id=0):
    """Generates step test data intended to mock api.swarming.trigger()

    Args:
      task_names (seq[str]): A sequence of task names representing the tasks we
        want to trigger.
      initial_id (int): The beginning of the ID range.
    """
    return self.m.json.output({
        'tasks': [{
            'task_id': '%d' % idx,
            'request': {
                'name': name,
            },
        } for idx, name in enumerate(task_names, start=initial_id)],
    })

  @staticmethod
  def task_result(id,
                  name,
                  state=TaskState.COMPLETED,
                  duration=62.35,
                  failure=False,
                  output='hello world!',
                  outputs=()):
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
      TaskState.INVALID, TaskState.PENDING, TaskState.RUNNING,
    ], 'state %s invalid or not final' % state.name
    if state == None:
      return {
        'error' : 'Bot could not be contacted',
        'results' : {'task_id' : id},
      }

    raw_results = {
        'output': output,
        'outputs': outputs,
        'results': {
          'name': name,
          'task_id': id,
          'state': state.name,
          'duration': duration,
          'outputs_ref': {
              'isolated': 'abc123',
              'isolatedserver': 'https://isolateserver.appspot.com',
              'namespace': 'default-gzip',
          },
        },
    }
    if state == TaskState.COMPLETED:
      raw_results['results']['exit_code'] = int(failure)

    return raw_results

  def collect(self, task_results):
    """Generates test step data for the swarming API collect method.

    Args:
      task_results (seq[dict]): A sequence of dicts encoding swarming task results.

    Returns:
      Step test data in the form of JSON output intended to mock a swarming API
      collect method call.
    """
    id_to_result = {result['results']['task_id'] : result for result in task_results}
    return self.m.json.output(id_to_result)
