#!/usr/bin/env python3
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import sys
import time
import os
import shutil

PID_FILE = sys.argv[1]
OUT_FILE = sys.argv[2]

while True:
  if os.path.isfile(PID_FILE):
    print("helper is running!")
    shutil.copyfile(PID_FILE, OUT_FILE)
    sys.exit(0)

  print("helper not running yet. Sleeping 1s")
  time.sleep(1)
