#!/usr/bin/env vpython
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import subprocess
import sys
import unittest

from repo_test_util import ROOT_DIR


class DocTest(unittest.TestCase):
  def test_doc(self):
    nul = open(os.devnull, 'w')

    script_path = os.path.join(ROOT_DIR, 'recipes.py')
    exit_code = subprocess.call([
        sys.executable, script_path,
        '--package', os.path.join(ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
        'doc'], stdout=nul, stderr=nul)
    self.assertEqual(0, exit_code)


if __name__ == '__main__':
  unittest.TestCase.maxDiff = None
  unittest.main()
