# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from recipe_engine import recipe_test_api

# TODO: make a real test api

class BuildbucketTestApi(recipe_test_api.RecipeTestApi):

  def simulated_buildbucket_output(self, additional_build_parameters):
    buildbucket_output = {
        'build':{
          'parameters_json': json.dumps(additional_build_parameters)
        }
    }

    return self.step_data(
        'buildbucket.get',
        stdout=self.m.raw_io.output_text(json.dumps(buildbucket_output)))

