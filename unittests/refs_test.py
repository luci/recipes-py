#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import subprocess
import unittest


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RefsTest(unittest.TestCase):
  def test_command(self):
    script_path = os.path.join(BASE_DIR, 'recipes.py')
    exit_code = subprocess.call([
        'python', script_path,
        '--package', os.path.join(BASE_DIR, 'infra', 'config', 'recipes.cfg'),
        'refs', 'step'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    self.assertEqual(0, exit_code)


if __name__ == '__main__':
  unittest.main()
