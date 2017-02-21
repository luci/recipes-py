#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import unittest

import test_env

from recipe_engine import config

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

class TestEnum(unittest.TestCase):
  def testEnum(self):
    schema = config.ConfigGroupSchema(test=config.Enum('foo', 'bar'))
    self.assertIsInstance(schema.new(test='foo'), config.ConfigGroup)

  def testMustBeOneOf(self):
    schema = config.ConfigGroupSchema(test=config.Enum('foo', 'bar'))
    with self.assertRaises(ValueError):
      schema.new(test='baz')

if __name__ == '__main__':
  unittest.main()
