#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class ShowMeTheModulesTest(unittest.TestCase):
  def testShowMeTheModules(self):
    scriptPath = os.path.join(BASE_DIR, 'show_me_the_modules.py')
    exitcode = subprocess.call(['python', scriptPath])
    self.assertEqual(0, exitcode)

if __name__ == '__main__':
  unittest.TestCase.maxDiff = None
  unittest.main()
