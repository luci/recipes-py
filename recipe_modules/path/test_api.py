from slave import recipe_test_api
from slave.recipe_config_types import Path, NamedBasePath

class PathTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def exists(*paths):
    assert all(isinstance(p, Path) for p in paths)
    return paths

  def __getitem__(self, name):
    return Path(NamedBasePath(name))

  def listdir(self, files):
    def listdir_callback():
      return self.m.json.output(files)
    return listdir_callback
