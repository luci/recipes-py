# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows test-repeatable access to a random UUID."""

import uuid

from recipe_engine import recipe_api

class UuidApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._fake_time = None
    self._fake_step = None
    if self._test_data.enabled:
      self._fake_uuid = self._test_data.get('seed', 4916)
      self._fake_step = self._test_data.get('step', 3)

  def random(self):
    """Returns a random UUID string."""
    if self._test_data.enabled:
      self._fake_uuid += self._fake_step
      return str(uuid.UUID(int=self._fake_uuid))
    return str(uuid.uuid4()) # pragma: no cover
