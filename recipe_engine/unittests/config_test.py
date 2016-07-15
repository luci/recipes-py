#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import unittest

import test_env

from recipe_engine import loader, recipe_api, config

class TestConfigGroupSchema(unittest.TestCase):
  def testNewReturnsConfigGroup(self):
    schema = config.ConfigGroupSchema(test=config.Single(int))

    self.assertIsInstance(schema.new(test=3), config.ConfigGroup)

  def testCallCallsNew(self):
    schema = config.ConfigGroupSchema(test=config.Single(int))
    sentinel = object()
    schema.new = lambda *args, **kwargs: sentinel

    self.assertEqual(schema(test=3), sentinel)

  def testMustHaveTypeMap(self):
    with self.assertRaises(ValueError):
      config.ConfigGroupSchema()

class TestProperties(unittest.TestCase):
  def testSimpleReturn(self):
    pass

if __name__ == '__main__':
  unittest.main()
