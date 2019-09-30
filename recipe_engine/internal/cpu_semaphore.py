# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from contextlib import contextmanager

import attr

from gevent.queue import Channel


@attr.s
class CPUResource(object):
  """Represents the machine's CPU as a limited resource.

  Each cpu (according to multiprocessing.cpu_count()) is worth 1000 millicores.
  Every subprocess that attempts to execute will first acquire its estimated
  amount of millicores before launching the subprocess. As soon as the
  subprocess completes, the held millicores are put back into the pool.

  Because recipes are finite both in runtime and number of distinct steps, this
  resource class unblocks other processes greedily. Whenever a subprocess
  completes, this analyzes all the outstanding subprocesses and will unblock
  whichever ones 'fit' in the now-freed resources. This is done in roughly FIFO
  order (i.e. if two tasks could potentially fit, the first one to block will be
  chosen over the second to unblock first).

  This is different than what's deemed 'fair' in a typical scheduling scenario,
  because in a mixed workload, heavy tasks could be forced to wait longer while
  small tasks use the CPU. However, because the recipes typically run with
  a hard finite timeout, it's better to use more of the CPU earlier than to
  potentially waste time waiting for small tasks to finish in order to schedule
  a heavy task earlier.
  """
  _millicores_available = attr.ib()

  _millicores_max = attr.ib()
  @_millicores_max.default
  def _millicores_max_default(self):
    return self._millicores_available

  # List[Tuple[amount, Channel]]
  _waiters = attr.ib(factory=list)

  @contextmanager
  def cpu(self, amount, call_if_blocking):
    """Block until `amount` of cpu, in millicores, is available.

    Requesting 0 cpu will never block or wait.
    Requesting < 0 cpu will raise ValueError.
    Requesting > _millicores_max will acquire the full CPU.

    Args:

      * amount (int) - The amount of millicores to acquire before yielding. Must
        be positive or will raise ValueError. If this exceeds the maximum amount
        of millicores available on the system, this will instead acquire the
        system maximum.
      * call_if_blocking (None|func(amount_blocked_on)) - `cpu` will invoke this
        callback if we would end up blocking before yielding. This callback
        should only be used for reporting/diagnostics (i.e. it shouldn't raise
        an exception.)

    Yields control once the requisite amount of cpu is available.
    """
    if amount < 0:
      raise ValueError('negative cpu amount')

    if amount > self._millicores_max:
      amount = self._millicores_max

    if amount > 0 and (self._waiters or self._millicores_available < amount):
      # we need some amount of cores AND
      # someone else is already waiting, or there aren't enough cores left.
      if call_if_blocking:
        call_if_blocking(amount - self._millicores_available)
      wake_me = Channel()
      self._waiters.append((amount, wake_me))
      wake_me.get()
      # At this point the greenlet that woke us already reserved our cores for
      # us, and we're free to go.
    else:
      # Just directly take our cores.
      assert self._millicores_available >= amount
      self._millicores_available -= amount

    try:
      yield
    finally:
      self._millicores_available += amount
      # We just added some resource back to the pot. Try to wake as many others
      # as we can before proceeding.

      to_wake, to_keep = [], []
      for waiting_amount, chan in self._waiters:
        if waiting_amount <= self._millicores_available:
          to_wake.append(chan)
          self._millicores_available -= waiting_amount
        else:
          to_keep.append((waiting_amount, chan))
      self._waiters = to_keep
      for chan in to_wake:
        chan.put(None)
