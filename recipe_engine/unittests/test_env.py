# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Module imported by other tests to automatically install a consistent test
enviornment.

This consists largely of system path manipulation.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from recipe_engine import env
