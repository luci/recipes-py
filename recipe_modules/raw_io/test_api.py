from recipe_engine import recipe_test_api

class RawIOTestApi(recipe_test_api.RecipeTestApi): # pragma: no cover
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None):
    return data, retcode

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output_dir(files_dict, retcode=None):
    assert type(files_dict) is dict
    assert all(type(key) is str for key in files_dict.keys())
    assert all(type(value) is str for value in files_dict.values())
    return files_dict, retcode

  def stream_output(self, data, stream='stdout', retcode=None):
    ret = recipe_test_api.StepTestData()
    assert stream in ('stdout', 'stderr')
    setattr(ret, stream, self.output(data, retcode).unwrap_placeholder())
    return ret
