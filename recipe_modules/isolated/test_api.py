# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class IsolatedTestApi(recipe_test_api.RecipeTestApi):

  @property
  def default_properties(self):
    return self.m.properties(**{
      '$recipe_engine/isolated': {
        'default_isolate_server': 'isolateserver.appspot.com',
        'isolated_version': 'release',
      },
    })

  def archive(self):
    return self.m.raw_io.output_text('[dummy hash]')
