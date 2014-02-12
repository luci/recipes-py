from slave import recipe_test_api

class RawIOTestApi(recipe_test_api.RecipeTestApi): # pragma: no cover
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None):
    return data, retcode
