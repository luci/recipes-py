from slave import recipe_test_api

class GeneratorScriptTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, script_name, *steps):
    assert all(isinstance(s, dict) for s in steps)
    return self.step_data(
      'gen step(%s)' % script_name,
      self.m.json.output(list(steps))
    )
