# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function

import signal
import sys
import os
import time


output_touchfile = sys.argv[0]
always_ignore = '--always-ignore' in sys.argv
install_hadler = '--no-handler' not in sys.argv


if install_hadler:
  def _handle(signum, _):
    if always_ignore:
      print("I GOT", signum)
    else:
      print("quitquitquit")
      os._exit(0)
  signal.signal(signal.SIGTERM, _handle)

begin = time.time()
end = begin + 99999
while time.time() < end:
  print("zzzzzz")
  time.sleep(1)
  os.utime(output_touchfile, None)

print("DONE?", time.time() - begin)
