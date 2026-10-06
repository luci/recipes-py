#!/usr/bin/env vpython3
# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Runs simulation tests and lint on the standard recipe modules."""

from __future__ import annotations

import os
import subprocess
import sys

import test_env

recipes_py = os.path.join(test_env.ROOT_DIR, 'recipes.py')

subprocess.check_call([sys.executable, recipes_py, 'test', 'run'])
subprocess.check_call([sys.executable, recipes_py, 'lint'])
