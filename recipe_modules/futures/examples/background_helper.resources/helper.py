# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os
import sys
import time

with open(sys.argv[1], 'wb') as pid_file:
  json.dump({
    # Note, you could put whatever connection information you wanted here.
    'pid': os.getpid(),
  }, pid_file)

for x in xrange(30):
  print "Hi! %s" % x
  time.sleep(1)
