# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib

from recipe_engine import recipe_api


class TempfileApi(recipe_api.RecipeApi):
  @contextlib.contextmanager
  def temp_dir(self, prefix):
    path = None
    try:
      path = self.m.path.mkdtemp(prefix)
      yield path
    finally:
      if path:
        self.m.shutil.rmtree(path, infra_step=True)
