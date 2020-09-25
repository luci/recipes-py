# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import recipe_test_api


class CasTestApi(recipe_test_api.RecipeTestApi):

  def properties(self, instance='example'):
    return self.m.properties(**{
        '$recipe_engine/cas': {
            'instance': instance,
        },
    })
