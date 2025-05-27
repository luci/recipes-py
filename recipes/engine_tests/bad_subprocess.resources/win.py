#!/usr/bin/env python3
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import sys
import subprocess

DETACHED_PROCESS = 0x00000008

print("parent")
sys.stdout.flush()
child = subprocess.Popen(['python3.exe', '-c', 'import time; time.sleep(30)'],
                         creationflags=DETACHED_PROCESS)
sys.stdout.flush()
print("parent leaves", child._handle, child.pid)
sys.exit(0)
