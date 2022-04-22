#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time
import sys

my_count = sys.argv[1]

for x in range(int(my_count)):
  print("Hi! %s" % x)
  time.sleep(1)

