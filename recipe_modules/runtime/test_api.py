# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class RuntimeTestApi(recipe_test_api.RecipeTestApi):

  def __call__(self, is_experimental=False):
    """Simulate runtime state of a build."""
    assert isinstance(is_experimental, bool), '%r (%s)' % (
        is_experimental, type(is_experimental))
    ret = self.test(None)
    ret.properties = {
      '$recipe_engine/runtime': {
        'is_experimental': is_experimental,
      },
    }
    return ret
