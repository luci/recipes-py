# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api

class StepApi(recipe_api.RecipeApi):
  def __init__(self, *args, **kwargs):
    self._auto_resolve_conflicts = False
    self._name_function = None
    self._step_names = {}
    super(StepApi, self).__init__(*args, **kwargs)

  # Making these properties makes them show up in show_me_the_modules,
  # and also makes it clear that they are intended to be mutated.
  @property
  def auto_resolve_conflicts(self):
    """Automatically resolve step name conflicts."""
    return self._auto_resolve_conflicts

  @auto_resolve_conflicts.setter
  def auto_resolve_conflicts(self, val):
    self._auto_resolve_conflicts = val

  def __call__(self, name, cmd, **kwargs):
    """Returns a step dictionary which is compatible with annotator.py.

    Args:
      name: The name of this step.
      cmd: A list of strings in the style of subprocess.Popen.
      **kwargs: Additional entries to add to the annotator.py step dictionary.

    Returns:
      A step dictionary which is compatible with annotator.py.
    """
    assert 'shell' not in kwargs
    assert isinstance(cmd, list)

    cmd = list(cmd)  # Create a copy in order to not alter the input argument.
    if self.auto_resolve_conflicts:
      step_count = self._step_names.setdefault(name, 0) + 1
      self._step_names[name] = step_count
      if step_count > 1:
        name = "%s (%d)" % (name, step_count)
    ret = kwargs
    ret.update({'name': name, 'cmd': cmd})
    return ret
