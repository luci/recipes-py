# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from recipe_engine import recipe_test_api

class JsonTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None, name=None):
    return json.dumps(data), retcode, name

  def output_stream(self, data, stream='stdout', retcode=None, name=None):
    assert stream in ('stdout', 'stderr')
    ret = recipe_test_api.StepTestData()
    step_data = self.output(data, retcode=retcode, name=name)
    setattr(ret, stream, step_data.unwrap_placeholder())
    return ret
