#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from recipe_engine import recipe_test_api

class EXC(Exception):
  pass

class TestExpectedException(unittest.TestCase):
  def testRecognizeException(self):
    """An expected exception is correctly recognized."""
    test_data = recipe_test_api.TestData()
    test_data.expect_exception(EXC.__name__)
    self.assertFalse(test_data.consumed)

    with test_data.should_raise_exception(EXC()) as should_raise:
      self.assertFalse(should_raise)

    with test_data.should_raise_exception(ValueError()) as should_raise:
      self.assertTrue(should_raise)

    self.assertTrue(test_data.consumed)

  def testNewException(self):
    """An unexpected exception results in being told to re-raise ."""
    test_data = recipe_test_api.TestData()
    self.assertTrue(test_data.consumed)

    with test_data.should_raise_exception(EXC()) as should_raise:
      self.assertTrue(should_raise)

    self.assertTrue(test_data.consumed)

  def testDisabledTestData(self):
    """Disabled test data correctly re-raises all exceptions."""
    test_data = recipe_test_api.TestData()

    with test_data.should_raise_exception(EXC()) as should_raise:
      self.assertTrue(should_raise)

if __name__ == '__main__':
  unittest.main()
