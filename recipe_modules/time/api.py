# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows mockable access to the current time."""

from recipe_engine import recipe_api

import datetime
import time

class TimeApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(TimeApi, self).__init__(**kwargs)
    self._fake_time = None
    self._fake_step = None
    if self._test_data.enabled:
      self._fake_time = self._test_data.get('seed', 1337000000.0)
      self._fake_step = self._test_data.get('step', 1.5)

  def sleep(self, secs):
    """Suspend execution of |secs| (float) seconds. Does nothing in testing.

    If secs > 60 (sleep longer than one minute), run a step to do the
    sleep, so that if a user looks at a build, they know what the recipe is
    doing.
    """
    if secs > 60: # pragma: no cover
      self.m.python.inline(
          'sleep',
          """
          import sys
          import time
          time.sleep(int(sys.argv[1]))
          """,
          args=[secs])
    else:
      if not self._test_data.enabled:  # pragma: no cover
        time.sleep(secs)

  def time(self):
    """Returns current timestamp as a float number of seconds since epoch."""
    if self._test_data.enabled:
      self._fake_time += self._fake_step
      return self._fake_time
    else:  # pragma: no cover
      return time.time()

  def ms_since_epoch(self):
    """Returns current timestamp as an int number of milliseconds since epoch.
    """
    return int(round(self.time() * 1000))

  def utcnow(self):
    """Returns current UTC time as a datetime.datetime."""
    if self._test_data.enabled:
      self._fake_time += self._fake_step
      return datetime.datetime.utcfromtimestamp(self._fake_time)
    else:  # pragma: no cover
      return datetime.datetime.utcnow()
