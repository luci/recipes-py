#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Runs simulation tests and lint on the standard recipe modules."""

import os
import subprocess

import repo_test_util
from repo_test_util import ROOT_DIR

def recipes_py(*args):
  subprocess.check_call([
      os.path.join(ROOT_DIR, 'recipes.py'), '--use-bootstrap',
      '--package', os.path.join(ROOT_DIR, 'infra', 'config', 'recipes.cfg')] +
      list(args))

# Run both current simulation test logic (simulation_test), and experimental
# (test). Eventually the former will be removed.
recipes_py('simulation_test')
recipes_py('test', 'run')

recipes_py('lint')
