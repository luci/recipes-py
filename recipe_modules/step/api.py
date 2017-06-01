# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib
import copy

from recipe_engine import recipe_api


# Inherit from RecipeApiPlain because the only thing which is a step is
# run_from_dict()
class StepApi(recipe_api.RecipeApiPlain):

  step_client = recipe_api.RequireClient('step')

  def __init__(self, step_properties, **kwargs):
    super(StepApi, self).__init__(**kwargs)
    self._step_names = {}
    self._seen_steps = set()
    self._prefix_path = step_properties.get('prefix_path', [])

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
    return self.step_client.previous_step_result()

  @contextlib.contextmanager
  def nest(self, name):
    """Nest allows you to nest steps hierarchically on the build UI.

    Calling

        with api.step.nest(<name>):
          ...

    will generate a dummy step with the provided name. All other steps run
    within this with statement will be hidden from the UI by default under this
    dummy step in a collapsible hierarchy. Nested blocks can also nest within
    each other.

    The nesting is implemented by adjusting the 'name' and 'nest_level' fields
    of the context (see the context() method above).
    """
    step_result = self(name, [])
    with self.m.context(name_prefix=name, increment_nest_level=True):
      yield step_result

  @property
  def defer_results(self):
    """ See recipe_api.py for docs. """
    return recipe_api.defer_results

  def __call__(self, name, cmd, ok_ret=None, infra_step=False, wrapper=(),
               timeout=None, allow_subannotations=None,
               trigger_specs=None, stdout=None, stderr=None, stdin=None,
               step_test_data=None):
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
      allow_subannotations (bool): if True, lets the step emit its own
          annotations. NOTE: Enabling this can cause some buggy behavior. Please
          strongly consider using step_result.presentation instead. If you have
          questions, please contact infra-dev@chromium.org.
      trigger_specs: a list of trigger specifications
      stdout: Placeholder to put step stdout into. If used, stdout won't appear
          in annotator's stdout (and |allow_subannotations| is ignored).
      stderr: Placeholder to put step stderr into. If used, stderr won't appear
          in annotator's stderr.
      stdin: Placeholder to read step stdin from.
      step_test_data (func -> recipe_test_api.StepTestData): A factory which
          returns a StepTestData object that will be used as the default test
          data for this step. The recipe author can override/augment this object
          in the GenTests function.

    Returns:
      Opaque step object produced and understood by recipe engine.
    """
    kwargs = {}
    if allow_subannotations is not None:
      kwargs['allow_subannotations'] = allow_subannotations
    if trigger_specs:
      kwargs['trigger_specs'] = trigger_specs
    if stdout:
      kwargs['stdout'] = stdout
    if stderr:
      kwargs['stderr'] = stderr
    if stdin:
      kwargs['stdin'] = stdin
    if step_test_data:
      kwargs['step_test_data'] = step_test_data
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

    # Calculate our full step name. If a step already has that name, add an
    # index to the end of it.
    #
    # Note that another step could exist with that index already added to it
    # by the user. If this happens, we'll continue appending indexes until we
    # have a unique step name.
    with self.m.context(name_prefix=name):
      base_name = self.m.context.name_prefix
    name_suffix = ''

    while True:
      full_name = base_name + name_suffix
      if full_name not in self._seen_steps:
        break

      step_count = self._step_names.setdefault(full_name, 1) + 1
      self._step_names[full_name] = step_count
      name_suffix = ' (%d)' % step_count
    self._seen_steps.add(full_name)

    cwd = self.m.context.cwd
    if cwd is not None and cwd != self.m.path['start_dir']:
      kwargs['cwd'] = cwd
    kwargs['env'] = self.m.context.env
    if self._prefix_path:
      ps = self.m.path.pathsep
      prefix = ps.join(self._prefix_path)
      suffix = kwargs['env'].get('PATH', '%(PATH)s')
      kwargs['env']['PATH'] = '%s%s%s' % (prefix, ps, suffix)
    kwargs['infra_step'] = self.m.context.infra_step or bool(infra_step)
    kwargs['step_nest_level'] = self.m.context.nest_level
    kwargs['name'] = full_name
    kwargs['base_name'] = name

    schema = self.make_config()
    schema.set_val(kwargs)
    return self.run_from_dict(schema.as_jsonish())

  # TODO(martiniss) delete, and make generator_script use **kwargs on step()
  @recipe_api.composite_step
  def run_from_dict(self, dct):
    return self.step_client.run_step(dct)
