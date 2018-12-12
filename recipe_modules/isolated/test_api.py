# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class IsolatedTestApi(recipe_test_api.RecipeTestApi):
  def properties(self,
                 server='https://example.isolateserver.appspot.com',
                 version='test_version'):
    return self.m.properties(**{
      '$recipe_engine/isolated': {
        'server': server,
        'version': version,
      },
    })

  def archive(self):
    return self.m.raw_io.output_text('[dummy hash]')
