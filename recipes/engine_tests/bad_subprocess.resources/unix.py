# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function


import os
import time
import sys

print("parent")
pid = os.fork()
if pid > 0:
  "parent leaves"
  sys.exit(0)

print("child")
pid = os.fork()
if pid > 0:
  "child leaves"
  sys.exit(0)

print("daemon sleepin'")
time.sleep(30)

print("ROAAARRRR!!!")
