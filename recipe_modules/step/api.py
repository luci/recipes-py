# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api
from slave import recipe_util

# Inherit from RecipeApiPlain because the only thing which is a step is
# run_from_dict()
class StepApi(recipe_api.RecipeApiPlain):
  EXCEPTION = 'EXCEPTION'
  FAILURE = 'FAILURE'
  SUCCESS = 'SUCCESS'
  WARNING = 'WARNING'

  @property
  def StepFailure(self):
    """ See recipe_api.py for docs. """
    return recipe_api.StepFailure

  @property
  def StepWarning(self):
    """ See recipe_api.py for docs. """
    return recipe_api.StepWarning #pragma: no cover

  @property
  def InfraFailure(self):
    """ See recipe_api.py for docs. """
    return recipe_api.InfraFailure

  @property
  def active_result(self):
    """The currently active (open) result from the last step that was run.

    Allows you to do things like:
      try:
        api.step('run test', [..., api.json.output()])
      finally:
        result = api.step.active_result
        if result.json.output:
          new_step_text = result.json.output['step_text']
          api.step.active_result.presentation.step_text = new_step_text

    This will update the step_text of the test, even if the test fails. Without
    this api, the above code would look like:

      try:
        result = api.step('run test', [..., api.json.output()])
      except api.StepFailure as f:
        result = f.result
        raise
      finally:
        if result.json.output:
          new_step_text = result.json.output['step_text']
          api.step.active_result.presentation.step_text = new_step_text
    """
    return self._engine.previous_step_result

  @property
  def defer_results(self):
    """ See recipe_api.py for docs. """
    return recipe_api.defer_results

  def __call__(self, name, cmd, ok_ret=None, infra_step=False, wrapper=(),
               **kwargs):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:
      name (string): The name of this step.
      cmd (list of strings): in the style of subprocess.Popen.
      ok_ret (tuple or set of ints, str): allowed return codes. Any unexpected
        return codes will cause an exception to be thrown. If you pass in the
        value 'any' or 'all', the engine will allow any return code to be
        returned. Defaults to {0}
      infra_step: Whether or not this is an infrastructure step. Infrastructure
        steps will place the step in an EXCEPTION state and raise InfraFailure.
      wrapper: If supplied, a command to prepend to the executed step as a
          command wrapper.
      **kwargs: Additional entries to add to the annotator.py step dictionary.

    Returns:
      Opaque step object produced and understood by recipe engine.
    """
    assert 'shell' not in kwargs
    assert isinstance(cmd, list)
    if not ok_ret:
      ok_ret = {0}
    if ok_ret in ('any', 'all'):
      ok_ret = set(range(-256, 256))

    command = list(wrapper)
    command += cmd

    kwargs.update({'name': name, 'cmd': command})
    kwargs['ok_ret'] = ok_ret
    kwargs['infra_step'] = bool(infra_step)

    schema = self.make_config()
    schema.set_val(kwargs)
    return self.run_from_dict(self._engine.create_step(schema))

  # TODO(martiniss) delete, and make generator_script use **kwargs on step()
  @recipe_api.composite_step
  def run_from_dict(self, dct):
    return self._engine.run_step(dct)
