# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api
from recipe_engine.config_types import Path, NamedBasePath

class PathTestApi(recipe_test_api.RecipeTestApi):
  def seed(self, seed):
    assert isinstance(seed, (int, long)), (
      'bad seed %s, expected (int, long)' % (type(seed),))
    ret = self.test(None)
    ret.properties = {'$recipe_engine/random': {'seed': seed}}
    return ret
