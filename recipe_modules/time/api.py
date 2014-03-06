# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from slave import recipe_api

import time

class TimeApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(TimeApi, self).__init__(**kwargs)
    self._fake_time = None
    self._fake_step = None
    if self._test_data.enabled:
      self._fake_time = self._test_data.get('seed', 1337000000.0)
      self._fake_step = self._test_data.get('step', 1.5)

  def time(self):
    """Return current timestamp as a float number of seconds since epoch."""
    if self._test_data.enabled:
      self._fake_time += self._fake_step
      return self._fake_time
    else:  # pragma: no cover
      return time.time()
