# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import json
import os
import sys
import time
import signal

def do_exit():
  print(">> CAUGHT SIGNAL, CLEANING UP", file=sys.stderr)
  time.sleep(2)
  print(">> DONE; EXITING", file=sys.stderr)
  sys.exit(0)

signal.signal(
    (
      signal.SIGBREAK  # pylint: disable=no-member
      if sys.platform.startswith('win') else
      signal.SIGTERM
    ),
    lambda _signum, _frame: do_exit())

print("Starting up!")
print(">> SLEEPING 5s", file=sys.stderr)
time.sleep(5)

with open(sys.argv[1], 'wb') as pid_file:
  json.dump({
    # Note, you could put whatever connection information you wanted here.
    'pid': os.getpid(),
  }, pid_file)
print(">> DUMPED PIDFILE", file=sys.stderr)

for x in xrange(30):
  print("Hi! %s" % x)
  time.sleep(1)
