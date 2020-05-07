#!/usr/bin/env python
# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys

if len(sys.argv) > 1:
  with open(sys.argv[1], 'wb') as f:
    f.write("""{"field": "hello"}""")
else:
  sys.stdout.write("""{"field": "cool stuff"}""")
