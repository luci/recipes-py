# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows mockable access to the current time."""

from recipe_engine import recipe_api

import datetime
import time

import gevent

from recipe_engine.internal.global_shutdown import GLOBAL_SHUTDOWN


class TimeApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super(TimeApi, self).__init__(**kwargs)
    self._fake_time = None
    self._fake_step = None
    if self._test_data.enabled:
      self._fake_time = self._test_data.get('seed', 1337000000.0)
      self._fake_step = self._test_data.get('step', 1.5)

  def sleep(self, secs, with_step=None, step_result=None):
    """Suspend execution of |secs| (float) seconds, waiting for GLOBAL_SHUTDOWN.
      Does nothing in testing.

    Args:
      * secs (number) - The number of seconds to sleep.
      * with_step (bool|None) - If True (or None and secs>60), emits a step to
        indicate to users that the recipe is sleeping (not just hanging). False
        suppresses this.
      * step_result (step_data.StepData|None) - Result of running a step. Should
        be None if with_step is True or None.
    """
    if with_step is True or (
        with_step is None and secs > 60): # pragma: no cover
      assert step_result is None, (
          'do not specify step_result if you want sleep to emit a new step')
      step_result = self.m.step.empty('sleep %d' % (secs,))

    if not self._test_data.enabled:  # pragma: no cover
      gevent.wait([GLOBAL_SHUTDOWN], timeout=secs)
    if GLOBAL_SHUTDOWN.ready() and step_result:
      step_result.presentation.status = "CANCELED"


    if GLOBAL_SHUTDOWN.ready() and step_result:
      step_result.presentation.status = "CANCELED"


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
