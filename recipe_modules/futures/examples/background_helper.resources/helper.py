# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os
import sys
import time
import signal

signal.signal(
    (
      signal.SIGBREAK  # pylint: disable=no-member
      if sys.platform.startswith('win') else
      signal.SIGTERM
    ),
    lambda _signum, _frame: sys.exit(0))

try:
  print "Starting up!"
  print >>sys.stderr, ">> SLEEPING 5s"
  time.sleep(5)

  with open(sys.argv[1], 'wb') as pid_file:
    json.dump({
      # Note, you could put whatever connection information you wanted here.
      'pid': os.getpid(),
    }, pid_file)
  print >>sys.stderr, ">> DUMPED PIDFILE"

  for x in xrange(30):
    print "Hi! %s" % x
    time.sleep(1)
except SystemExit:
  print >>sys.stderr, ">> QUITQUITQUIT"
  raise
