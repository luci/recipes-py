#!/usr/bin/env python
# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess
import unittest


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DepgraphTest(unittest.TestCase):
  def test_doc(self):
    script_path = os.path.join(BASE_DIR, 'recipes.py')
    exit_code = subprocess.call([
        'python', script_path,
        '--package', os.path.join(BASE_DIR, 'infra', 'config', 'recipes.cfg'),
        'depgraph'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    self.assertEqual(0, exit_code)


if __name__ == '__main__':
  unittest.TestCase.maxDiff = None
  unittest.main()
