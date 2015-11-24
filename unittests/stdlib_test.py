#!/usr/bin/env python

"""Runs simulation tests and lint on the standard recipe modules."""

import os
import subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def recipes_py(*args):
  subprocess.check_call([
      os.path.join(ROOT_DIR, 'recipes.py'),
      '--package', os.path.join(ROOT_DIR, 'infra', 'config', 'recipes.cfg')] +
      list(args))

recipes_py('simulation_test', '--threshold=91')
recipes_py('lint')
