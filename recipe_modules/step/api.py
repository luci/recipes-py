# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib

from recipe_engine import recipe_api


# Inherit from RecipeApiPlain because the only thing which is a step is
# run_from_dict()
class StepApi(recipe_api.RecipeApiPlain):
  def __init__(self, **kwargs):
    super(StepApi, self).__init__(**kwargs)
    self._step_names = {}
    self._seen_steps = set()

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
    return recipe_api.StepWarning

  @property
  def InfraFailure(self):
    """ See recipe_api.py for docs. """
    return recipe_api.InfraFailure

  @property
  def StepTimeout(self):
    """ See recipe_api.py for docs. """
    return recipe_api.StepTimeout

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
  def context(self):
    """ See recipe_api.py for docs. """
    return recipe_api.context

  @contextlib.contextmanager
  def nest(self, name):
    """Nest is the high-level interface to annotated hierarchical steps.

    Calling

        with api.step.nest(<name>):
          ...

    will generate a dummy step and implicitly create a new context (as
    above); the dummy step will govern annotation emission, while the implicit
    context will propagate the dummy step's name to subordinate steps.
    """
    step_result = self(name, [])
    context_dict = {'name': name, 'nest_level': 1}
    with self.context(context_dict):
      yield step_result

  @property
  def defer_results(self):
    """ See recipe_api.py for docs. """
    return recipe_api.defer_results

  def __call__(self, name, cmd, ok_ret=None, infra_step=False, wrapper=(),
               timeout=None, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:
      name (string): The name of this step.
      cmd (list of strings): in the style of subprocess.Popen or None to create
        a no-op fake step.
      ok_ret (tuple or set of ints, str): allowed return codes. Any unexpected
        return codes will cause an exception to be thrown. If you pass in the
        value 'any' or 'all', the engine will allow any return code to be
        returned. Defaults to {0}
      infra_step: Whether or not this is an infrastructure step. Infrastructure
        steps will place the step in an EXCEPTION state and raise InfraFailure.
      wrapper: If supplied, a command to prepend to the executed step as a
        command wrapper.
      timeout: If supplied, the recipe engine will kill the step after the
        specified number of seconds.
      **kwargs: Additional entries to add to the annotator.py step dictionary.

    Returns:
      Opaque step object produced and understood by recipe engine.
    """
    assert 'shell' not in kwargs
    assert cmd is None or isinstance(cmd, list)
    if not ok_ret:
      ok_ret = {0}
    if ok_ret in ('any', 'all'):
      ok_ret = set(range(-256, 256))

    if cmd is not None:
      command = list(wrapper)
      command += cmd
      kwargs['cmd'] = command

    kwargs['timeout'] = timeout
    kwargs['ok_ret'] = ok_ret

    # Obtain information from composite step parent.
    compositor = recipe_api._STEP_CONTEXT

    # Calculate our full step name. If a step already has that name, add an
    # index to the end of it.
    #
    # Note that another step could exist with that index already added to it
    # by the user. If this happens, we'll continue appending indexes until we
    # have a unique step name.
    while True:
      full_name = compositor.get_with_context('name', name)
      if full_name not in self._seen_steps:
        break

      step_count = self._step_names.setdefault(full_name, 1) + 1
      self._step_names[full_name] = step_count
      name = "%s (%d)" % (name, step_count)
    self._seen_steps.add(full_name)

    if 'cwd' not in kwargs:
      kwargs['cwd'] = compositor.get('cwd')
    kwargs['env'] = compositor.get_with_context('env', kwargs.get('env', {}))
    kwargs['infra_step'] = compositor.get_with_context(
        'infra_step', bool(infra_step))
    kwargs['step_nest_level'] = compositor.get_with_context('nest_level', 0)
    kwargs['name'] = full_name

    schema = self.make_config()
    schema.set_val(kwargs)
    return self.run_from_dict(self._engine.create_step(schema))

  # TODO(martiniss) delete, and make generator_script use **kwargs on step()
  @recipe_api.composite_step
  def run_from_dict(self, dct):
    return self._engine.run_step(dct)
