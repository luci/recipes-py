#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from recipe_engine import recipe_test_api

class TestExpectedException(unittest.TestCase):
  def testRecognizeException(self):
    """Tests that an expected exception is correctly recognized."""
    class EXC(Exception):
      pass

    test_data = recipe_test_api.TestData()
    test_data.expect_exception(EXC.__name__)
    self.assertFalse(test_data.consumed)

    with test_data.should_raise_exception(EXC()) as should_raise:
      self.assertFalse(should_raise)

    self.assertTrue(test_data.consumed)

  def testNewException(self):
    """Tests that an unexpected exception results in being told to re-raise ."""
    test_data = recipe_test_api.TestData()
    self.assertTrue(test_data.consumed)

    with test_data.should_raise_exception(ValueError()) as should_raise:
      self.assertTrue(should_raise)

    self.assertTrue(test_data.consumed)

if __name__ == '__main__':
  unittest.main()
