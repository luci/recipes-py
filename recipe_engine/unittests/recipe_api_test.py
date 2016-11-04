#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import unittest

import test_env

from recipe_engine import recipe_api, config

def make_prop(**kwargs):
  name = kwargs.pop('name', "dumb_name")
  return recipe_api.Property(**kwargs).bind(name, 'test', 'properties_test')

class TestProperties(unittest.TestCase):
  def testDefault(self):
    """Tests the default option of properties."""
    for default in (1, object(), "test", None):
      prop = make_prop(default=default)
      self.assertEqual(default, prop.interpret(recipe_api.PROPERTY_SENTINEL))

  def testRequired(self):
    """Tests that a required property errors when not provided."""
    prop = make_prop()
    with self.assertRaises(ValueError):
      prop.interpret(recipe_api.PROPERTY_SENTINEL)

  def testTypeSingle(self):
    """Tests a simple typed property."""
    prop = make_prop(kind=bool)
    with self.assertRaises(TypeError):
      prop.interpret(1)

    self.assertEqual(True, prop.interpret(True))

  def testTypeFancy(self):
    """Tests a config style type property."""
    prop = make_prop(kind=config.List(int))
    for value in (1, "hi", [3, "test"]):
      with self.assertRaises(TypeError):
        prop.interpret(value)

    self.assertEqual([2, 3], prop.interpret([2, 3]))

  def testValidTypes(self):
    check = recipe_api.BoundProperty.legal_name

    for test, result, is_param_name in (
        ('', False, False),
        ('.', False, False),
        ('foo', True, False),
        ('event.patchSet.ref', True, False),
        ('event.patchSet.ref', False, True),
        ('rietveld_url', True, False),):
      self.assertEqual(
          check(test, is_param_name=is_param_name), result,
          "name {} should be {}. is_param_name={}".format(
              test, result, is_param_name))

  def testParamName(self):
    """Tests the default param name is the regular name."""
    prop = recipe_api.Property()
    bound = prop.bind('a')

    self.assertEqual('a', bound.param_name)

  def testParamName(self):
    """
    Tests setting a param name correctly carries through to a bound property.
    """
    prop = recipe_api.Property(param_name='b')
    bound = prop.bind('a', 'test', 'test_me')

    self.assertEqual('b', bound.param_name)

  def testParamNameDotted(self):
    """
    Tests setting a param name correctly carries through to a bound property.
    """
    prop = recipe_api.Property(param_name='good_name')
    bound = prop.bind('bad.name-time', 'test', 'test_me')

    self.assertEqual('good_name', bound.param_name)


if __name__ == '__main__':
  unittest.main()
