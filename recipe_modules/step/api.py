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

  # Making these properties makes them show up in show_me_the_modules,
  # and also makes it clear that they are intended to be mutated.
  @property
  def auto_resolve_conflicts(self):
    """Automatically resolve step name conflicts."""
    return self._auto_resolve_conflicts

  @auto_resolve_conflicts.setter
  def auto_resolve_conflicts(self, val):
    self._auto_resolve_conflicts = val

  def __call__(self, name, cmd, ok_ret=None, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:
      name: The name of this step.
      cmd: A list of strings in the style of subprocess.Popen.
      ok_ret: A tuple or set of allowed return codes. Any unexpected return
        codes will cause an exception to be thrown. If you pass in the value
        |any| or |all|, the engine will allow any return code to be returned.
        Defaults to {0}
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

    schema = self.make_config()
    schema.set_val(kwargs)
    return self.run_from_dict(self._engine.create_step(schema))

  # TODO(martiniss) delete, and make generator_script use **kwargs on step()
  def run_from_dict(self, dct):
    return self._engine.run_step(dct)
