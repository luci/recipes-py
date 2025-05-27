#!/usr/bin/env python3
# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import time
import sys
amt = int(sys.argv[1])
print("taking a %d sec nap" % amt)
time.sleep(amt)
print("awake again!")
