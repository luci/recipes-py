# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Allows mockable access to the current time."""

from __future__ import annotations

import datetime
import functools
import time
from typing import TypeVar

import gevent
from recipe_engine import recipe_api
from recipe_engine.internal.global_shutdown import GLOBAL_SHUTDOWN

ReturnType = TypeVar('ReturnType')


class exponential_retry:
  """Decorator which retries the function with exponential backoff.

  See TimeApi.exponential_retry for full documentation.
  """

  def __init__(self, retries: int,
               delay: datetime.timedelta,
               condition: Callable[[Exception], bool] | None = None,
               time_api: TimeApi = None):
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
    # NOTE: Because the decorator can exist as module-level state, it is
    # important that these values are READ-ONLY. Writing to them will act like
    # assigning a global variable for that particular instance of the decorator,
    # meaning that multiple different tests running in the same process could
    # save arbitrary data which crosses between test cases.
    self.time_api = time_api
    self.retries = retries
    self.delay = delay
    self.condition = condition or (lambda e: True)

  def __call__(self,
               f: Callable[[...], ReturnType]) -> Callable[[...], ReturnType]:
    @functools.wraps(f)
    def wrapper(*args, **kwargs) -> ReturnType:
      time_api = self.time_api
      if time_api is None:
        try:
          time_api = args[0].m.time
          err_msg = "Could not find TimeAPI module. " \
            "See docs for recipe_engine/time.exponential_retry for usage."
          assert isinstance(time_api, TimeApi), err_msg
        except:
          raise

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
          to_sleep = time_api._jitter(to_sleep, .15)
          time_api.sleep(to_sleep)
          retry_delay *= 2
    return wrapper


class TimeApi(recipe_api.RecipeApi):
  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._fake_time: float | None = None
    self._fake_step: float | None = None
    if self._test_data.enabled:
      self._fake_time = self._test_data.get('seed', 1337000000.0)
      self._fake_step = self._test_data.get('step', 1.5)

  def sleep(self, secs: float | int, with_step: bool | None = None,
            step_result: step_data.StepData | None = None) -> None:
    """Suspend execution of |secs| (float) seconds, waiting for GLOBAL_SHUTDOWN.
      Does nothing in testing.

    Args:
      * secs - The number of seconds to sleep.
      * with_step - If True, emits a step to indicate to users that the recipe is
        sleeping (not just hanging). If None, then will default to True if
        sleeping for a long time (>60sec); this can be disabled by setting
        explicitly to None. If the GLOBAL_SHUTDOWN event has already occurred,
        then a step will always be emitted in order to force raising an
        exception.
      * step_result - Result of running a step. Should be None if with_step is
        True or None.
    """
    if with_step is True or GLOBAL_SHUTDOWN.ready() or (
        with_step is None and secs > 60):  # pragma: no cover
      assert step_result is None, (
          'do not specify step_result if you want sleep to emit a new step')
      step_result = self.m.step.empty('sleep %d' % (secs,))

    if not self._test_data.enabled:  # pragma: no cover
      gevent.wait([GLOBAL_SHUTDOWN], timeout=secs)

  def exponential_retry(
      self,
      retries: int,
      delay: datetime.timedelta,
      condition: Callable[[Exception], bool] = None,
  ) -> exponential_retry:
    """Adds exponential retry to a function.

    Decorator which retries the function with exponential backoff.

    Each time the decorated function throws an exception, we sleep for some
    amount of time. We increase the amount of time exponentially to prevent
    cascading failures from overwhelming systems. We also add a jitter to avoid
    the thundering herd problem.

    Example usage:

    ```
    def RunSteps(api):
      @api.time.exponential_retry(5, datetime.timedelta(seconds=1))
      def test_retries():
        api.step('running', None)
        raise Exception()

      test_retries()
      # Executes 6 steps with 'running' as a common prefix of their step names.
    ```

    When writing a recipe module whose method needs to be retried, you won't
    have access to the time module in the class body, but you can import a
    class-method decorator like:

      from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

    This decorator can be used on class methods or on functions
    (for example, functions in a recipe file).

    NOTE: Your module/recipe MUST ALSO depend on
          "recipe_engine/time" in its DEPS.

    NOTE: For non-class-method functions, the first parameter to those functions
          must be an api object, such as the passed to RunSteps.

    Example usage 1 (class method decorator):

    ```
    from recipe_engine.recipe_api import RecipeApi
    from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

    # NOTE: Don't forget to put "recipe_engine/time" in the module DEPS.

    class MyRecipeModule(RecipeApi):
        @exponential_retry(5, datetime.timedelta(seconds=1))
        def my_retriable_function(self, ...):
            self.m.step('running', None)
    ```

    Example usage 2 (function with api as first arg):

    ```
    from RECIPE_MODULES.recipe_engine.time.api import exponential_retry

    # NOTE: Don't forget to put "recipe_engine/time" in DEPS.

    @exponential_retry(5, datetime.timedelta(seconds=1))
    def helper_function(api):
      api.step('running', None)

    def RunSteps(api):
      helper_funciton(api)
    ```
    """
    return exponential_retry(retries, delay, condition, self)

  def time(self) -> float:
    """Returns current timestamp as a float number of seconds since epoch."""
    if self._test_data.enabled:
      self._fake_time += self._fake_step
      return self._fake_time
    else:  # pragma: no cover
      return time.time()

  def ms_since_epoch(self) -> int:
    """Returns current timestamp as an int number of milliseconds since epoch.
    """
    return int(round(self.time() * 1000))

  def utcnow(self) -> datetime.datetime:
    """Returns current UTC time as a datetime.datetime."""
    if self._test_data.enabled:
      self._fake_time += self._fake_step
      return datetime.datetime.utcfromtimestamp(self._fake_time)
    else:  # pragma: no cover
      return datetime.datetime.utcnow()

  def _jitter(self, seconds: float, jitter_amount: float,
              random_func: Callable[[], float] | None = None) -> float:
    """Returns the provided seconds jittered by the jitter amount provided.

    random_func allows for manually providing the random value in tests.
    """
    if not random_func:
      random_func = self.m.random.random
    return seconds * (1 + random_func() * (jitter_amount * 2) - jitter_amount)

  def timeout(self, seconds: float | int | datetime.timedelta = None):
    """Provides a context that times out after the given time.

    Usage:
    with api.time.timeout(datetime.timedelta(minutes=5)):
      # your steps

    Look at the "deadline" section of https://chromium.googlesource.com/infra/luci/luci-py/+/HEAD/client/LUCI_CONTEXT.md
    to see how this works.

    If the new deadline would be later than the old deadline (if any), the
    deadline will not be updated, making this a no-op. For example, if
    `api.time.timeout(timedelta(minutes=10))` is used in a builder that has a
    5-minute execution timeout, it will not have any effect.
    """

    if isinstance(seconds, datetime.timedelta):
      seconds = seconds.total_seconds()

    if seconds < 0:
      raise recipe_api.StepFailure('`seconds` cannot be negative')
    current_time = self.time()

    # Update the deadline, but make sure not to extend it since that's not
    # allowed and would raise an exception. Raising an exception is undesirable
    # because the code that calls `timeout()` may run in different situations
    # (different recipes or builders) with different higher-level timeouts, so
    # just because the timeout is a no-op in one situation doesn't mean it won't
    # have an effect in other situations.
    #
    # Plus, this function is generally only used to increase the strictness of
    # the time limit for a sequence of operations, so if the time limit is
    # already stricter than requested, it's reasonable to no-op.
    new_deadline = current_time + seconds
    dl = self.m.context.deadline
    if not dl.soft_deadline or new_deadline < dl.soft_deadline:
      dl.soft_deadline = new_deadline

    return self.m.context(deadline=dl)
