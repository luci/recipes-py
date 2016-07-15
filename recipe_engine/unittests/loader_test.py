#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import unittest

import test_env

from recipe_engine import loader, recipe_api, config
import mock


class TestRecipeScript(unittest.TestCase):
  def testReturnSchemaHasValidClass(self):
    with self.assertRaises(ValueError):
      script = loader.RecipeScript({'RETURN_SCHEMA': 3}, 'test_script')

  def testSetsAttributes(self):
    sentinel = object()
    script = loader.RecipeScript({'imarandomnamelala': sentinel}, 'test_script')
    self.assertEqual(sentinel, script.imarandomnamelala)

  def testRunChecksReturnType(self):
    sentinel = object()
    mocked_return = object()
    class FakeReturn(object):
      def as_jsonish(_self, hidden=sentinel):
        self.assertEqual(True, hidden)

        return mocked_return

    script = loader.RecipeScript({
        'RETURN_SCHEMA': config.ConfigGroupSchema(a=config.Single(int)),
        'RunSteps': None,
    }, 'test_script')
    loader.invoke_with_properties = lambda *args, **kwargs: FakeReturn()

    self.assertEqual(mocked_return, script.run(None, None))

def make_prop(**kwargs):
  name = kwargs.pop('name', "dumb_name")
  return recipe_api.Property(**kwargs).bind(name, 'test', 'properties_test')


class TestInvoke(unittest.TestCase):
  def invoke(self, callable, all_properties, prop_defs, arg_names, **kwargs):
    return loader._invoke_with_properties(
        callable, all_properties, prop_defs, arg_names, **kwargs)

  def testInvokeFuncSimple(self):
    """Simple test of invoke."""
    def func():
      pass

    self.assertEqual(self.invoke(func, {}, {}, []), None)

  def testInvokeFuncComplex(self):
    """Tests invoke with two different properties."""
    def func(a, b): # pylint: disable=unused-argument
      return a

    prop_defs = {
      'a': make_prop(name="a"),
      'b': make_prop(name="b"),
    }

    props = {
      'a': 1,
      'b': 2,
    }
    self.assertEqual(1, self.invoke(func, props, prop_defs, ['a', 'b']))

  def testInvokeParamName(self):
    """Tests invoke with a param name."""
    def func(c):
      return c

    prop_defs = {
      'b.a': make_prop(name="c", param_name="c"),
    }

    props = {
      'b.a': 2,
    }
    self.assertEqual(2, self.invoke(func, props, prop_defs, ['c']))

  def testInvokeClass(self):
    """Tests invoking a class."""
    class test(object):
      def __init__(self, a, b): # pylint: disable=unused-argument
        self.answer = a

    prop_defs = {
      'a': make_prop(name="a"),
      'b': make_prop(name="b"),
    }

    props = {
      'a': 1,
      'b': 2,
    }
    self.assertEqual(1, self.invoke(test, props, prop_defs, ['a', 'b']).answer)

  def testMissingProperty(self):
    """Tests that invoke raises an error when missing a property."""
    def func(a):
      return a

    with self.assertRaises(recipe_api.UndefinedPropertyException):
      self.invoke(func, {}, {}, ['a'])

  def testMustBeBound(self):
    """Tests that calling invoke with a non BoundProperty fails."""
    prop_defs = {
      "a": recipe_api.Property()
    }

    with self.assertRaises(ValueError):
      self.invoke(None, None, prop_defs, ['a'])

  def testInvokeArgNamesFunc(self):
    def test_function(a, b):
      return a

    with mock.patch(
        'recipe_engine.loader._invoke_with_properties') as mocked_invoke:
      loader.invoke_with_properties(test_function, None, None)
      args, _ = mocked_invoke.call_args
      self.assertTrue(['a', 'b'] in args)

  def testInvokeArgNamesClass(self):
    class TestClass(object):
      def __init__(self, api, foo, bar):
        pass

    with mock.patch(
        'recipe_engine.loader._invoke_with_properties') as mocked_invoke:
      loader.invoke_with_properties(TestClass, None, None)
      args, _ = mocked_invoke.call_args
      self.assertTrue(['api', 'foo', 'bar'] in args)


if __name__ == '__main__':
  unittest.main()
