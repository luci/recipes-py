# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

# TODO(phajdan.jr): Move applicable methods from build repo's file module here.
class ShutilApi(recipe_api.RecipeApi):
  def rmtree(self, path, **kwargs):
    self.m.python.inline(
        'rmtree %s' % path,
        """
          import shutil, sys
          shutil.rmtree(sys.argv[1])
        """,
        args=[path],
        **kwargs)
