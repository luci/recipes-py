#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from recipe_engine import loader, recipe_api, config

class TestProperties(unittest.TestCase):
  def _makeProp(self, *args, **kwargs):
    return recipe_api.Property(*args, **kwargs)

  def testDefault(self):
    """Tests the default option of properties."""
    for default in (1, object(), "test", None):
      prop = self._makeProp(default=default)
      self.assertEqual(default, prop.interpret(recipe_api.Property.sentinel))

  def testRequired(self):
    """Tests that a required property errors when not provided."""
    prop = self._makeProp()
    with self.assertRaises(ValueError):
      prop.interpret(recipe_api.Property.sentinel)

  def testTypeSingle(self):
    """Tests a simple typed property."""
    prop = self._makeProp(kind=bool)
    with self.assertRaises(TypeError):
      prop.interpret(1)

    self.assertEqual(True, prop.interpret(True))

  def testTypeFancy(self):
    """Tests a config style type property."""
    prop = self._makeProp(kind=config.List(int))
    for value in (1, "hi", [3, "test"]):
      with self.assertRaises(TypeError):
        prop.interpret(value)

    self.assertEqual([2, 3], prop.interpret([2, 3]))

class TestInvoke(unittest.TestCase):
  def invoke(self, callable, all_properties, prop_defs, **kwargs):
    return loader.invoke_with_properties(
        callable, all_properties, prop_defs, **kwargs)

  def testInvokeFuncSimple(self):
    """Simple test of invoke."""
    def func():
      pass

    self.assertEqual(self.invoke(func, {}, {}), None)

  def testInvokeFuncComplex(self):
    """Tests invoke with two different properties."""
    def func(a, b):
      return a

    prop_defs = {
      'a': recipe_api.Property(),
      'b': recipe_api.Property(),
    }

    props = {
      'a': 1,
      'b': 2,
    }
    self.assertEqual(1, self.invoke(func, props, prop_defs))

  def testInvokeClass(self):
    """Tests invoking a class."""
    class test(object):
      def __init__(self, a, b):
        self.answer = a

    prop_defs = {
      'a': recipe_api.Property(),
      'b': recipe_api.Property(),
    }

    props = {
      'a': 1,
      'b': 2,
    }
    self.assertEqual(1, self.invoke(test, props, prop_defs).answer)

  def testMissingProperty(self):
    """Tests that invoke raises an error when missing a property."""
    def func(a):
      return a

    with self.assertRaises(recipe_api.UndefinedPropertyException):
      self.invoke(func, {}, {})

if __name__ == '__main__':
  unittest.main()
