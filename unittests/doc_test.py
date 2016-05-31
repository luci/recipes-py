#!/usr/bin/env python
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class DocTest(unittest.TestCase):
  def test_doc(self):
    script_path = os.path.join(BASE_DIR, 'recipes.py')
    exit_code = subprocess.call([
        'python', script_path,
        '--package', os.path.join(BASE_DIR, 'infra', 'config', 'recipes.cfg'),
        'doc'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    self.assertEqual(0, exit_code)

  def test_info(self):
    script_path = os.path.join(BASE_DIR, 'recipes.py')
    exit_code = subprocess.call([
        'python', script_path,
        '--package', os.path.join(BASE_DIR, 'infra', 'config', 'recipes.cfg'),
        'info', '--recipes-dir'])
      #stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    self.assertEqual(0, exit_code)

if __name__ == '__main__':
  unittest.TestCase.maxDiff = None
  unittest.main()
