# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api

class GeneratorScriptApi(recipe_api.RecipeApi):
  def __call__(self, path_to_script, *args, **kwargs):
    """Run a script and generate the steps emitted by that script.

    If a step has a key 'outputs_presentation_json' whose value is
    True, its command is extended with a --presentation-json argument
    pointing to a file where it is expected to write presentation json
    which is used to update that step's presentation on the waterfall.

    Presentation keys are:
      logs: A map of log names to log text.
      links: A map of link text to URIs.
      perf_logs: A map of log names to text.
      step_summary_text: A string to set as the step summary.
      step_text: A string to set as the step text.
      properties: A map of build_property names to JSON-encoded values.

    kwargs:
      env - The environment for the generated steps.
    """
    f = '--output-json'
    step_name = 'gen step(%s)' % self.m.path.basename(path_to_script)

    step_test_data = kwargs.pop('step_test_data', None)
    if str(path_to_script).endswith('.py'):
      step_result = self.m.python(
        step_name,
        path_to_script, list(args) + [f, self.m.json.output()],
        cwd=self.m.path['checkout'], step_test_data=step_test_data)
    else:
      step_result = self.m.step(
        step_name,
        [path_to_script,] + list(args) + [f, self.m.json.output()],
        cwd=self.m.path['checkout'], step_test_data=step_test_data)
    new_steps = step_result.json.output
    assert isinstance(new_steps, list)
    env = kwargs.get('env')

    for step in new_steps:
      if env:
        new_env = env.copy()
        new_env.update(step.get('env', {}))
        step['env'] = new_env
      outputs_json = step.pop('outputs_presentation_json', False)
      if outputs_json:
        # This step has requested a JSON file which the binary that
        # it invokes can write to, so provide it with one.
        step['cmd'].extend(['--presentation-json', self.m.json.output(False)])

      #TODO(martiniss) change this to use a regular step call
      step['ok_ret'] = set(step.pop('ok_ret', {0}))
      step_result = self.m.step.run_from_dict(step)

      if outputs_json:
        p = step_result.presentation
        j = step_result.json.output

        if j:
          p.logs.update(j.get('logs', {}))
          p.links.update(j.get('links', {}))
          p.perf_logs.update(j.get('perf_logs', {}))
          p.step_summary_text = j.get('step_summary_text', '')
          p.step_text = j.get('step_text', '')
          p.properties.update(j.get('properties', {}))
