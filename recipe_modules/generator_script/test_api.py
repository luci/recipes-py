# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

class GeneratorScriptTestApi(recipe_test_api.RecipeTestApi):
  def __call__(self, script_name, *steps):
    assert all(isinstance(s, dict) for s in steps)
    return self.step_data(
      'gen step(%s)' % script_name,
      self.m.json.output(list(steps))
    )
