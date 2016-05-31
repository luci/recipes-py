# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class ShutilTestApi(recipe_test_api.RecipeTestApi):
  def listdir(self, files):
    def listdir_callback():
      return self.m.json.output(files)
    return listdir_callback
