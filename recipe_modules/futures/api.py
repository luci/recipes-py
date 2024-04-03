# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Implements in-recipe concurrency via green threads."""

import gevent
import gevent.lock
import gevent.queue

import attr
from attr.validators import instance_of

from recipe_engine.recipe_api import RecipeApi, RequireClient
from recipe_engine.recipe_api import escape_all_warnings


class _IWaitWrapper:
  __slots__ = ('_waiter', '_greenlets_to_futures')

  def __init__(self, futures, timeout, count):
    # pylint: disable=protected-access
    self._greenlets_to_futures = {fut._greenlet: fut for fut in futures}
    self._waiter = gevent.iwait(
        list(self._greenlets_to_futures.keys()), timeout, count)

  def __enter__(self):
    self._waiter.__enter__()
    return self

  def __exit__(self, typ, value, tback):
    return self._waiter.__exit__(typ, value, tback)

  def __iter__(self):
    return self

  def __next__(self):
    return self._greenlets_to_futures[self._waiter.__next__()]

  next = __next__


class FuturesApi(RecipeApi):
  """Provides access to the Recipe concurrency primitives."""
  concurrency_client = RequireClient('concurrency')

  def __init__(self, *args, **kwargs):
    super(FuturesApi, self).__init__(*args, **kwargs)
    self._future_id = 0

  class Timeout(Exception):
    """Raised from Future if the requested operation is not done in time."""

  @attr.s(frozen=True, slots=True)
  class Future:
    """Represents a unit of concurrent work.

    Modeled after Python 3's `concurrent.futures.Future`. We can expand this
    API carefully as we need it.
    """

    _greenlet = attr.ib(
        validator=instance_of(gevent.Greenlet))  # type: gevent.Greenlet

    # We would use _greenlet.name for this, except that it's automatically
    # generated names are not going to be unique within the recipe run. So, we
    # keep our own counter and assign a UID if the user didn't pass __name.
    _name = attr.ib()

    _meta = attr.ib()

    @property
    def name(self):
      """Returns the name of this Future.

      The name is either the string provided with `__name` at spawn time, or is
      generated like "Future-%d", where the %d is a globally sequential and
      unique number which is guaranteed not to be reused within the same recipe
      run.

      This makes `name` useful for tracking Future objects when getting them
      back from e.g. iwait.

      Also see `meta` to directly attach metadata to this Future.
      """
      return self._name

    @property
    def meta(self):
      """Returns metadata associated with this Future.

      This metadata must have been associated with the Future at spawn time with
      the `__meta` kwarg.

      The meta object is not interpreted or used by the recipe engine in any
      way. You are free to mutate the meta object, if you wish, but you cannot
      assign to it. e.g.

         fut = api.futures.spawn(..., __meta={'key': 'value'})
         fut.meta                    #=> {'key': 'value'}
         fut.meta['thing'] = 100     # OK
         fut.meta = "something else" # FAIL
      """
      return self._meta

    def result(self, timeout=None):
      """Blocks until this Future is done, then returns its value, or raises
      its exception.

      Args:
        * timeout (None|seconds) - How long to wait for the Future to be done.

      Returns the result if the Future is done.

      Raises the Future's exception, if the Future is done with an error.

      Raises Timeout if the Future is not done within the given timeout.
      """
      with gevent.Timeout(timeout, exception=FuturesApi.Timeout()):
        return self._greenlet.get()

    @property
    def done(self):
      """Property set to True iff this Future is no longer running."""
      return self._greenlet.dead

    def cancel(self):
      """Raises GreenletExit in the underlying greenlet.

      If the greenlet is waiting on a subprocess (step), the subprocess will be
      killed, and the step's ExecutionResult will have `was_cancelled=True`.
      This will then raise an InfraFailure exception within the greenlet.

      Does not block on the death of the greenlet.
      Does not switch away from the current greenlet.
      """
      self._greenlet.kill()

    def exception(self, timeout=None):
      """Blocks until this Future is done, then returns (not raises) this
      Future's exception (or None if there was no exception).

      Args:
        * timeout (None|seconds) - How long to wait for the Future to be done.

      Returns the exception instance which would be raised from `result` if
      the Future is Done, otherwise None.

      Raises Timeout if the Future is not done within the given timeout.
      """
      with gevent.Timeout(timeout, exception=FuturesApi.Timeout()):
        done = gevent.wait([self._greenlet])[0]
        return done.exception

  def make_bounded_semaphore(self, value=1):
    """Returns a gevent.BoundedSemaphore with depth `value`.

    This can be used as a context-manager to create concurrency-limited sections
    like:

        def worker(api, sem, i):
          with api.step.nest('worker %d' % i):
            with sem:
              api.step('one at a time', ...)

            api.step('unrestricted concurrency' , ...)

        sem = api.future.make_semaphore()
        for i in xrange(100):
          api.futures.spawn(fn, sem, i)

    NOTE: If you use the BoundedSemaphore without the context-manager syntax, it
    could lead to difficult-to-debug deadlocks in your recipe.

    NOTE: This method will raise ValueError if used with @@@annotation@@@ mode.
    """
    if not self.concurrency_client.supports_concurrency: # pragma: no cover
      # test mode always supports concurrency, hence the nocover
      raise ValueError('BoundedSemaphore not allowed in @@@annotation@@@ mode')
    return gevent.lock.BoundedSemaphore(value=value)

  def make_channel(self):
    """Returns a single-slot communication device for passing data and control
    between concurrent functions.

    This is useful for running 'background helper' type concurrent processes.

    NOTE: It is strongly discouraged to pass Channel objects outside of a recipe
    module. Access to the channel should be mediated via
    a class/contextmanager/function which you return to the caller, and the
    caller can call in a makes-sense-for-your-moudle's-API way.

    See ./tests/background_helper.py for an example of how to use a Channel
    correctly.

    It is VERY RARE to need to use a Channel. You should avoid using this unless
    you carefully consider and avoid the possibility of introducing deadlocks.

    NOTE: This method will raise ValueError if used with @@@annotation@@@ mode.
    """
    if not self.concurrency_client.supports_concurrency: # pragma: no cover
      # test mode always supports concurrency, hence the nocover
      raise ValueError('Channels are not allowed in @@@annotation@@@ mode')
    return gevent.queue.Channel()

  @escape_all_warnings
  def spawn(self, func, *args, **kwargs):
    """Prepares a Future to run `func(*args, **kwargs)` concurrently.

    Any steps executed in `func` will only have manipulable StepPresentation
    within the scope of the executed function.

    Because this will spawn a greenlet on the same OS thread (and not,
    for example a different OS thread or process), `func` can easily be an
    inner function, closure, lambda, etc. In particular, func, args and kwargs
    do not need to be pickle-able.

    This function does NOT switch to the greenlet (you'll have to block on a
    future/step for that to happen). In particular, this means that the
    following pattern is safe:

        # self._my_future check + spawn + assignment is atomic because
        # no switch points occur.
        if not self._my_future:
          self._my_future = api.futures.spawn(func)

    NOTE: If used in @@@annotator@@@ mode, this will block on the completion of
    the Future before returning it.

    Kwargs:

      * __name (str) - If provided, will assign this name to the spawned
        greenlet. Useful if this greenlet ends up raising an exception, this
        name will appear in the stderr logging for the engine. See
        `Future.name` for more information.
      * __meta (any) - If provided, will assign this metadata to the returned
        Future. This field is for your exclusive use.
      * Everything else is passed to `func`.

    Returns a Future of `func`'s result.
    """
    name = kwargs.pop('__name', None)
    if name is None:
      name = 'Future-%d' % (self._future_id,)
    self._future_id += 1

    meta = kwargs.pop('__meta', None)

    ret = self.Future(self.concurrency_client.spawn(
        func, args, kwargs, name), name, meta)
    if not self.concurrency_client.supports_concurrency: # pragma: no cover
      # test mode always supports concurrency, hence the nocover
      self.wait([ret])
    return ret

  @escape_all_warnings
  def spawn_immediate(self, func, *args, **kwargs):
    """Returns a Future to the concurrently running `func(*args, **kwargs)`.

    This is like `spawn`, except that it IMMEDIATELY switches to the new
    Greenlet. You may want to use this if you want to e.g. launch a background
    step and then another step which waits for the daemon.

    Kwargs:

      * __name (str) - If provided, will assign this name to the spawned
        greenlet. Useful if this greenlet ends up raising an exception, this
        name will appear in the stderr logging for the engine. See
        `Future.name` for more information.
      * __meta (any) - If provided, will assign this metadata to the returned
        Future. This field is for your exclusive use.
      * Everything else is passed to `func`.

    Returns a Future of `func`'s result.
    """
    name = kwargs.pop('__name', None)
    meta = kwargs.pop('__meta', None)
    chan = self.make_channel()
    @escape_all_warnings
    def _immediate_runner():
      chan.get()
      return func(*args, **kwargs)
    ret = self.spawn(_immediate_runner, __name=name, __meta=meta)
    chan.put(None)  # Pass execution to _immediate_runner
    return ret

  @staticmethod
  def wait(futures, timeout=None, count=None):
    """Blocks until `count` `futures` are done (or timeout occurs) then
    returns the list of done futures.

    This is analogous to `gevent.wait`.

    Args:
      * futures (List[Future]) - The Future objects to wait for.
      * timeout (None|seconds) - How long to wait for the Futures to be done.
        If we hit the timeout, wait will return even if we haven't reached
        `count` Futures yet.
      * count (None|int) - The number of Futures to wait to be done. If None,
        waits for all of them.

    Returns the list of done Futures, in the order in which they were done.
    """
    return list(_IWaitWrapper(futures, timeout, count))

  @staticmethod
  def iwait(futures, timeout=None, count=None):
    """Iteratively yield up to `count` Futures as they become done.


    This is analogous to `gevent.iwait`.

    Usage:

        for future in api.futures.iwait(futures):
          # consume future

    If you are not planning to consume the entire iwait iterator, you can
    avoid the resource leak by doing, for example:

        with api.futures.iwait(a, b, c) as iter:
          for future in iter:
            if future is a:
              break

    You might want to use `iwait` over `wait` if you want to process a group
    of Futures in the order in which they complete. Compare:

      for task in iwait(swarming_tasks):
        # task is done, do something with it

      vs

      while swarming_tasks:
        task = wait(swarming_tasks, count=1)[0]  # some task is done
        swarming_tasks.remove(task)
        # do something with it

    Args:
      * futures (List[Future]) - The Future objects to wait for.
      * timeout (None|seconds) - How long to wait for the Futures to be done.
      * count (None|int) - The number of Futures to yield. If None,
        yields all of them.

    Yields futures in the order in which they complete until we hit the
    timeout or count. May also be used with a context manager to avoid
    leaking resources if you don't plan on consuming the entire iterable.
    """
    return _IWaitWrapper(futures, timeout, count)
