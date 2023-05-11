#!/usr/bin/env python3
# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys

dump_dir = sys.argv[1]
os.mkdir(os.path.join(dump_dir, 'some'))
with open(os.path.join(dump_dir, 'some', 'file'), 'w', encoding='utf-8') as o1:
  o1.write('cool contents')
with open(os.path.join(dump_dir, 'other_file'), 'w', encoding='utf-8') as o2:
  o2.write('whatever')
