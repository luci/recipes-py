# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows mockable access to the current time."""

from recipe_engine import recipe_api

import datetime
import functools
import time

import gevent

from recipe_engine.internal.global_shutdown import GLOBAL_SHUTDOWN


class exponential_retry(object):
  """Decorator which retries the function with exponential backoff.

  Each time the decorated function throws an exception, we sleep for some amount
  of time. We increase the amount of time exponentially to prevent cascading
  failures from overwhelming systems. We also add a jitter to avoid the
  thundering herd problem.

  Example usage:

  def RunSteps(api):
    @api.time.exponential_retry(5, datetime.timedelta(seconds=1))
    def test_retries():
      api.step('running', None)
      raise Exception()

    test_retries()
    # Executes 6 steps with 'running' as a common prefix of their step names.

  You cannot use this when you define recipe module methods, since the recipe
  dependency tree has not been instantiated when those methods are being
  defined. You should instead wrap any individual operation which should be
  retried in a small function which uses this decorator. If this becomes
  commonly used, additional functionality to this module could be added to
  support this use case.
  """

  def __init__(self, time_api, retries, delay, condition=None):
    """Creates a new exponential retry decorator.

    Args:
      time_api (TimeApi): A TimeApi instance. Used to sleep.
      retries (int): Maximum number of retries before giving up.
          This value controls the number of *retries*, not the number of total
          executions of the function.
          If you decorate a function with a value of 3 retries, the function
          will execute a maximum of 4 times; 1 time initially, and 3 more times
          as it gets retried 3 times.
      delay (datetime.timedelta): Amount of time to wait before retrying. This
          will double every retry attempt (exponential).
          This delay is 'jittered' to avoid the 'thundering herd' problem
          (https://en.wikipedia.org/wiki/Thundering_herd_problem).
          We only sleep in integral seconds, so sub-second resolution is not
          supported for delays.
      condition (func): If not None, a function that will be passed the
          exception as its one argument. Retries will only happen if this
          function returns True. If None, retries will always happen.
    """
    self.time_api = time_api
    self.retries = retries
    self.delay = delay
    self.condition = condition or (lambda e: True)

  def __call__(self, f):

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
      retry_delay = self.delay
      # We want to retry self.retries times, so we make the range give us
      # exactly self.retries loop executions.
      for i in range(self.retries + 1):
        try:
          return f(*args, **kwargs)
        except Exception as e:
          if i >= self.retries or not self.condition(e):
            raise
          to_sleep = retry_delay.total_seconds()
          # Jitter the amount to sleep by plus or minus 15%.
          # Jitter helps avoid
          # https://en.wikipedia.org/wiki/Thundering_herd_problem
          to_sleep *= 1 + self.time_api.m.random.random() / .3 - .15
          self.time_api.sleep(to_sleep)
          retry_delay *= 2

    return wrapper


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

  def exponential_retry(self, retries, delay, condition=None):
    """Adds exponential retry to a function.

    See the 'exponential_retry' function in this module for more docs.
    """
    return exponential_retry(self, retries, delay, condition)

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
