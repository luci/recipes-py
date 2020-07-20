#!/usr/bin/env python
# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys

dump_dir = sys.argv[1]
os.mkdir(os.path.join(dump_dir, 'some'))
with open(os.path.join(dump_dir, 'some', 'file'), 'w') as f:
  f.write('cool contents')
with open(os.path.join(dump_dir, 'other_file'), 'w') as f:
  f.write('whatever')
