# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class SwarmingTestApi(recipe_test_api.RecipeTestApi):
  def properties(self,
                 server='https://example.swarmingserver.appspot.com',
                 version='test_version'):
    return self.m.properties(**{
      '$recipe_engine/isolated': {
        'server': server,
        'version': version,
      },
    })

  def trigger(self, task_names):
    """Generates step test data intended to mock api.swarming.trigger()

    Args:
      task_names (seq[str]): A sequence of task names representing the tasks we
        want to trigger.
    """
    return self.m.json.output({
        'tasks': [{
            'task_id': '%d' % idx,
            'request': {
                'name': name,
            },
        } for idx, name in enumerate(task_names)],
    })
