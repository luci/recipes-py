# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Simplistic temporary directory manager (deprecated)."""

import contextlib

from recipe_engine import recipe_api


class TempfileApi(recipe_api.RecipeApi):
  @contextlib.contextmanager
  def temp_dir(self, prefix):
    """This makes a temporary directory which lives for the scope of the with
    statement.

    Example:
    ```python
    with api.tempfile.temp_dir("some_prefix") as path:
      # use path
    # path is deleted here.
    ```
    """
    path = None
    try:
      path = self.m.path.mkdtemp(prefix)
      yield path
    finally:
      if path:
        self.m.file.rmtree('rmtree %s' % path, path)
