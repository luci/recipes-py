# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_api


class LedApi(recipe_api.RecipeApi):
  """Interface to the led tool.

  "led" stands for LUCI editor. It allows users to debug and modify LUCI jobs.
  It can be used to modify many aspects of a LUCI build, most commonly including
  the recipes used.

  The main interface this module provides is a direct call to the led binary:

    led_result = api.led(
      'get-builder', ['luci.chromium.try:chromium_presubmit'])
    final_data = led_result.then('edit-recipe-bundle').result

  See the led binary for full documentation of commands.
  """

  class LedResult(object):
    """Holds the result of a led operation. Can be chained using |then|."""
    def __init__(self, result, module):
      self._result = result
      self._module = module

    @property
    def result(self):
      """The mutable result data of the previous led call as decoded JSON."""
      return self._result

    def then(self, *cmd):
      """Invoke led, passing it the current `result` data as input.

      Returns another LedResult object with the output of the command.
      """
      return self.__class__(
          self._module._run_command(self._result, *cmd).stdout, self._module)

  def __init__(self, **kwargs):
    super(LedApi, self).__init__(**kwargs)
    self._led_path = None

  @property
  def _led_binary_path(self):
    """The path to the led binary on disk."""
    return self._led_path.join('led')

  def __call__(self, *cmd):
    """Runs led with the given arguments. Wraps result in a `LedResult`."""
    return self.LedResult(self._run_command(None, *cmd).stdout, self)

  def _run_command(self, previous, *cmd):
    """Runs led with a given command and arguments.

    Args:
      cmd: The led command to run, e.g. 'get-builder', 'edit', along with any
        arguments.
      previous: The previous led step's json result, if any. This can be
        used to chain led commands together. See the tests for an example of
        this.

    Ensures that led is checked out on disk before trying to execute the
    command.
    """
    self._ensure_led()

    kwargs = {
      'stdout': self.m.json.output(),
    }

    if previous:
      kwargs['stdin'] = self.m.json.input(data=previous)

    result = self.m.step(
        'led %s' % cmd[0], [self._led_binary_path]  + list(cmd), **kwargs)

    # If we launched a task, add a link to the swarming task.
    if cmd[0] == 'launch':
      result.presentation.links['Swarming task'] = 'https://%s/task?id=%s' % (
          result.stdout['swarming']['host_name'],
          result.stdout['swarming']['task_id'])
    return result

  def _ensure_led(self):
    """Ensures that led is checked out on disk.

    Sets _led_path as a side-effect. This will always use `[CACHE]/led` as the
    location of the unpacked binaries.
    """
    if self._led_path:
      return

    ensure_file = self.m.cipd.EnsureFile().add_package(
        'infra/tools/luci/led/${platform}', 'latest')
    led_path = self.m.path['cache'].join('led')
    self.m.cipd.ensure(led_path, ensure_file)

    self._led_path = led_path
