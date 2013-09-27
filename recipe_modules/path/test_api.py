from slave import recipe_test_api

class PathTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def exists(*paths):
    return paths
