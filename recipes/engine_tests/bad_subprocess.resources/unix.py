#!/usr/bin/env python3
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import os
import time
import sys

print("parent")
pid = os.fork()
if pid > 0:
  print("parent leaves")
  sys.exit(0)

print("child")
pid = os.fork()
if pid > 0:
  print("child leaves")
  sys.exit(0)

print("daemon sleepin'")
time.sleep(30)

print("ROAAARRRR!!!")
