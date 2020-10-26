# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import logging
import os
import sys
import time

from contextlib import contextmanager

from recipe_engine.third_party import luci_context

from google.protobuf import json_format as jsonpb

import gevent
import gevent.signal as signal
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

# UNKILLED_PGIDS is a global set of process groups which haven't been SIGKILL'd
# yet.
#
# This is manipulated by step_runner/subproc on *nix and unused on windows.
UNKILLED_PGIDS = set()


LOG = logging.getLogger(__name__)


@contextmanager
def install_signal_handlers():
  """Sets up a the global terminator greenlet to:

    * Set GLOBAL_SHUTDOWN on an interrupt signal or after the
      LUCI_CONTEXT['deadline']['soft_deadline']-.5 timestamp.
    * Set GLOBAL_QUITQUITQUIT after the next interrupt signal or after
      LUCI_CONTEXT['deadline']['grace_period']-.5 seconds.

  Sets LUCI_CONTEXT['deadline'] for the duration of this contextmanager.
  """
  d = sections_pb2.Deadline()
  deadline_raw = luci_context.read('deadline')
  if deadline_raw:
    d = jsonpb.ParseDict(deadline_raw, d)
  else:
    # per LUCI_CONTEXT spec. missing deadline means presumed 30s grace period.
    d.grace_period = 30

  d.grace_period = max(d.grace_period, 0)
  d.soft_deadline = max(d.soft_deadline, 0)

  # now adjust deadline to reserve .5 of deadline/grace_period for any processes
  # the engine launches.
  if d.grace_period > .5:
    d.grace_period -= .5
  if d.soft_deadline > .5:
    d.soft_deadline -= .5

  def _terminator_greenlet():
    if d.soft_deadline:
      now = time.time()
      if d.soft_deadline > now:
        gevent.wait([GLOBAL_SHUTDOWN], timeout=(d.soft_deadline - now))
        GLOBAL_SHUTDOWN.set()
    else:
      GLOBAL_SHUTDOWN.wait()
    LOG.info('Initiating GLOBAL_SHUTDOWN')

    gevent.wait([GLOBAL_QUITQUITQUIT], timeout=d.grace_period)
    GLOBAL_QUITQUITQUIT.set()
    LOG.info('Initiating GLOBAL_QUITQUITQUIT')
    for pgid in UNKILLED_PGIDS:
      try:
        os.killpg(pgid, signal.SIGKILL)
      except OSError as ex:
        LOG.warning('killpg(%d, SIGKILL): %s' % (pgid, ex))

  term_greenlet = gevent.spawn(_terminator_greenlet)

  def _set_shutdown(signum, _frame):
    LOG.info('"Got signal (%d)' % (signum,))
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
    gevent.wait([term_greenlet])
