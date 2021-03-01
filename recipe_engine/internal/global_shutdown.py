# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import errno
import logging
import os
import signal
import sys
import time

from contextlib import contextmanager

from recipe_engine.third_party import luci_context

from google.protobuf import json_format as jsonpb

import gevent
import gevent.event

from PB.go.chromium.org.luci.lucictx import sections as sections_pb2


MSWINDOWS = sys.platform.startswith(('win', 'cygwin'))

_INTERRUPT_SIGNALS = [signal.SIGINT, signal.SIGTERM]
if MSWINDOWS:
  _INTERRUPT_SIGNALS.append(signal.SIGBREAK)


# GLOBAL_SHUTDOWN is set on the first SIGTERM and means that the recipe is in
# global shutdown mode; All running steps will start the "graceful kill"
# process, and no new steps will be able to launch.
#
# This event is only installed for real runs of the recipe; It blocks forever
# for test mode.
GLOBAL_SHUTDOWN = gevent.event.Event()

# GLOBAL_QUITQUITQUIT is set on the second SIGTERM and means that the recipe is
# in global emergency teardown mode; All running steps in the "graceful kill"
# process will switch to immediately kill their subprocesses.
#
# If GLOBAL_QUITQUITQUIT is set, it implies that GLOBAL_SHUTDOWN is also set.
#
# This event is only installed for real runs of the recipe; It blocks forever
# for test mode.
GLOBAL_QUITQUITQUIT = gevent.event.Event()


# GLOBAL_SOFT_DEADLINE holds the raw soft_deadline value from outside the
# recipe engine process. This is used to determine if we should apply an
# explicit timeout to steps, or not.
GLOBAL_SOFT_DEADLINE = 0.0
_lc_raw_deadline = luci_context.read('deadline')
if _lc_raw_deadline and 'soft_deadline' in _lc_raw_deadline:
  GLOBAL_SOFT_DEADLINE = _lc_raw_deadline['soft_deadline']
del _lc_raw_deadline

# UNKILLED_PGIDS is a global set of process groups which haven't been SIGKILL'd
# yet.
#
# This is manipulated by step_runner/subproc on *nix and unused on windows.
UNKILLED_PGIDS = set()


LOG = logging.getLogger(__name__)


@contextmanager
def install_signal_handlers():
  """Sets up a the global terminator greenlet to:

    * Set GLOBAL_SHUTDOWN on an interrupt signal (which should occur at
      LUCI_CONTEXT['deadline']['soft_deadline'], OR if the build is canceled).
    * Set GLOBAL_QUITQUITQUIT after LUCI_CONTEXT['deadline']['grace_period']-1
      seconds after GLOBAL_SHUTDOWN.

  Sets LUCI_CONTEXT['deadline'] for the duration of this contextmanager.
  """
  d = sections_pb2.Deadline()
  deadline_raw = luci_context.read('deadline')
  if deadline_raw:
    d = jsonpb.ParseDict(deadline_raw, d)
  else:
    # per LUCI_CONTEXT spec. missing deadline means presumed 30s grace period.
    d.grace_period = 30

  # now adjust deadline to reserve 1 second of grace_period for any processes
  # the engine launches. This should give the engine sufficient time to killpg
  # any stray process groups.
  d.grace_period = max(d.grace_period - 1, 0)

  # terminator_greenlet reacts to signal from parent, which occurs during
  # cancelation or timeout.
  def _terminator_greenlet():
    GLOBAL_SHUTDOWN.wait()
    gevent.wait([GLOBAL_QUITQUITQUIT], timeout=d.grace_period)
    if not GLOBAL_QUITQUITQUIT.ready():
      LOG.info('Setting GLOBAL_QUITQUITQUIT')
      GLOBAL_QUITQUITQUIT.set()
    else:
      LOG.info('Engine quitting normally')
    for pgid in UNKILLED_PGIDS:
      try:
        os.killpg(pgid, signal.SIGKILL)
      except OSError as ex:
        # ESRCH: process group doesn't exist
        if ex.errno != errno.ESRCH:
          LOG.warning('killpg(%d, SIGKILL): %s' % (pgid, ex))

  terminator_greenlet = gevent.spawn(_terminator_greenlet)

  def _set_shutdown(signum, _frame):
    LOG.info('Got signal (%d), Setting GLOBAL_SHUTDOWN', signum)
    GLOBAL_SHUTDOWN.set()

  old_handlers = [
    signal.signal(signum, _set_shutdown)
    for signum in _INTERRUPT_SIGNALS
  ]

  try:
    with luci_context.write('deadline', jsonpb.MessageToDict(d)):
      yield
  finally:
    for signum, old_handler in zip(_INTERRUPT_SIGNALS, old_handlers):
      signal.signal(signum, old_handler)

    # By this point we needn't have any mercy; All steps have returned so any
    # dangling groups are fair game.
    GLOBAL_SHUTDOWN.set()
    GLOBAL_QUITQUITQUIT.set()
    terminator_greenlet.get()
