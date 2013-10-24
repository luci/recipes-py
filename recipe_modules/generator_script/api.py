# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api

class GeneratorScriptApi(recipe_api.RecipeApi):
  def __call__(self, path_to_script, *args, **kwargs):
    """Run a script and generate the steps emitted by that script.

    kwargs:
      env - The environment for the generated steps.
    """
    f = '--output-json'
    step_name = 'gen step(%s)' % self.m.path.basename(path_to_script)
    if str(path_to_script).endswith('.py'):
      yield self.m.python(
        step_name,
        path_to_script, list(args) + [f, self.m.json.output()],
        cwd=self.m.path.checkout)
    else:
      yield self.m.step(
        step_name,
        [path_to_script,] + list(args) + [f, self.m.json.output()],
        cwd=self.m.path.checkout)
    new_steps = self.m.step_history.last_step().json.output
    assert isinstance(new_steps, list)
    env = kwargs.get('env')
    if env:
      for step in new_steps:
        new_env = env.copy()
        new_env.update(step.get('env', {}))
        step['env'] = new_env
    yield new_steps
