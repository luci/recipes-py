#!/usr/bin/env vpython3
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Runs simulation tests and lint on the standard recipe modules."""

import os
import sys

from subprocess import check_call

from test_env import ROOT_DIR

recipes_py = os.path.join(ROOT_DIR, 'recipes.py')

check_call([sys.executable, recipes_py, 'test', 'run'])
check_call([sys.executable, recipes_py, 'lint'])
