from slave import recipe_test_api

class RawIOTestApi(recipe_test_api.RecipeTestApi): # pragma: no cover
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None):
    return data, retcode

  def stream_output(self, data, stream='stdout', retcode=None):
    ret = recipe_test_api.StepTestData()
    assert stream in ('stdout', 'stderr')
    setattr(ret, stream, self.output(data, retcode).unwrap_placeholder())
    return ret
