# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api
from slave import recipe_util

class StepApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(StepApi, self).__init__(**kwargs)
    self._auto_resolve_conflicts = False
    self._name_function = None
    self._step_names = {}

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

  # Making these properties makes them show up in show_me_the_modules,
  # and also makes it clear that they are intended to be mutated.
  @property
  def auto_resolve_conflicts(self):
    """Automatically resolve step name conflicts."""
    return self._auto_resolve_conflicts

  @auto_resolve_conflicts.setter
  def auto_resolve_conflicts(self, val):
    self._auto_resolve_conflicts = val

  @recipe_api.composite_step
  def __call__(self, name, cmd, ok_ret=None, infra_step=False, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:
      name: The name of this step.
      cmd: A list of strings in the style of subprocess.Popen.
      ok_ret: A tuple or set of allowed return codes. Any unexpected return
        codes will cause an exception to be thrown. If you pass in the value
        |any| or |all|, the engine will allow any return code to be returned.
        Defaults to {0}
      infra_step: Whether or not this is an infrastructure step. Infrastructure
        steps will place the step in an EXCEPTION state and raise InfraFailure.
      **kwargs: Additional entries to add to the annotator.py step dictionary.

    Returns:
      Opaque step object produced and understood by recipe engine.
    """
    assert 'shell' not in kwargs
    assert isinstance(cmd, list)
    if not ok_ret:
      ok_ret = {0}
    if ok_ret in (any, all):
      ok_ret = set(range(-256, 256))

    cmd = list(cmd)  # Create a copy in order to not alter the input argument.
    if self.auto_resolve_conflicts:
      step_count = self._step_names.setdefault(name, 0) + 1
      self._step_names[name] = step_count
      if step_count > 1:
        name = "%s (%d)" % (name, step_count)
    kwargs.update({'name': name, 'cmd': cmd})
    kwargs['ok_ret'] = ok_ret
    kwargs['infra_step'] = bool(infra_step)

    schema = self.make_config()
    schema.set_val(kwargs)
    return self.run_from_dict(self._engine.create_step(schema))

  # TODO(martiniss) delete, and make generator_script use **kwargs on step()
  def run_from_dict(self, dct):
    return self._engine.run_step(dct)
