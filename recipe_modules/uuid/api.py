# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import uuid

from recipe_engine import recipe_api

class UuidApi(recipe_api.RecipeApi):
  def random(self):
    """Generates and returns a random UUID as a string."""
    if self._test_data.enabled:
      return '00000000-0000-0000-0000-000000000000'
    else: # pragma: no cover
      return str(uuid.uuid4())

