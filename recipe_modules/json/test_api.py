# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json

from recipe_engine import recipe_test_api

from .api import dumps

class JsonTestApi(recipe_test_api.RecipeTestApi):
  @staticmethod
  def dumps(*args, **kwargs):
    return dumps(*args, **kwargs)

  @recipe_test_api.placeholder_step_data
  @staticmethod
  def output(data, retcode=None, name=None):
    """Supplies placeholder data for a json.output. `data` should be a jsonish
    python object (e.g. dict, list, str, bool, int, etc). It will be dumped out
    with json.dumps and the step will be observed to return that dumped value.
    """
    return json.dumps(data), retcode, name

  def invalid(self, raw_data_str, retcode=None, name=None):
    """Can be used to supply data for a json.output, except that it takes a raw
    string rather than a json object."""
    ret = recipe_test_api.StepTestData()
    ret.retcode=retcode
    placeholder_data = recipe_test_api.PlaceholderTestData(
      data=raw_data_str, name=name)
    ret.placeholder_data[(self._module.NAME, 'output', name)] = placeholder_data
    return ret

  def output_stream(self, data, stream='stdout', retcode=None, name=None):
    assert stream in ('stdout', 'stderr')
    ret = recipe_test_api.StepTestData()
    step_data = self.output(data, retcode=retcode, name=name)
    setattr(ret, stream, step_data.unwrap_placeholder())
    return ret
