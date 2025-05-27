#!/usr/bin/env python3
# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import sys
import json


with open(sys.argv[1], 'rb') as f:
  assert json.load(f) == {"field": "sup"}
