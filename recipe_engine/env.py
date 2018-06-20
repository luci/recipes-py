# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Sets up recipe engine Python environment."""

import os
import sys

# Hook up our third party vendored packages.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIRD_PARTY = os.path.join(BASE_DIR, 'recipe_engine', 'third_party')


# Install local imports.
sys.path = [
    THIRD_PARTY,
    os.path.join(THIRD_PARTY, 'client-py')
] + sys.path
