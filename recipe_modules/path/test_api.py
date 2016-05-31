# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api
from recipe_engine.config_types import Path, NamedBasePath

class PathTestApi(recipe_test_api.RecipeTestApi):
  @recipe_test_api.mod_test_data
  @staticmethod
  def exists(*paths):
    assert all(isinstance(p, Path) for p in paths)
    return paths

  def __getitem__(self, name):
    return Path(NamedBasePath(name))
