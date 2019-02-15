#!/usr/bin/env vpython
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import test_env

from recipe_engine import recipe_api, config


RECIPE_PROPERTY = recipe_api.BoundProperty.RECIPE_PROPERTY
MODULE_PROPERTY = recipe_api.BoundProperty.MODULE_PROPERTY


def make_prop(**kwargs):
  name = kwargs.pop('name', "dumb_name")
  return recipe_api.Property(**kwargs).bind(
    name, RECIPE_PROPERTY, 'fake_repo::fake_recipe')


class TestProperties(test_env.RecipeEngineUnitTest):
  def testDefault(self):
    """Tests the default option of properties."""
    for val in (1, {}, "test", None):
      prop = make_prop(default=val)
      self.assertEqual(val, prop.interpret(recipe_api.PROPERTY_SENTINEL, {}))

  def testRequired(self):
    """Tests that a required property errors when not provided."""
    prop = make_prop()
    with self.assertRaises(ValueError):
      prop.interpret(recipe_api.PROPERTY_SENTINEL, {})

  def testTypeSingle(self):
    """Tests a simple typed property."""
    prop = make_prop(kind=bool)
    with self.assertRaises(TypeError):
      prop.interpret(1, {})

    self.assertEqual(True, prop.interpret(True, {}))

  def testTypeFancy(self):
    """Tests a config style type property."""
    prop = make_prop(kind=config.List(int))
    for value in (1, "hi", [3, "test"]):
      with self.assertRaises(TypeError):
        prop.interpret(value, {})

    self.assertEqual([2, 3], prop.interpret([2, 3], {}))

  def testFromEnviron(self):
    """Tests that properties can pick up values from environment."""
    prop = make_prop(default='def', from_environ='ENV_VAR')

    # Nothing is given => falls back to hardcoded default.
    self.assertEqual('def', prop.interpret(recipe_api.PROPERTY_SENTINEL, {}))
    # Only env var is given => uses it.
    self.assertEqual(
        'var', prop.interpret(recipe_api.PROPERTY_SENTINEL, {'ENV_VAR': 'var'}))
    # Explicit values is given => uses it.
    self.assertEqual('value', prop.interpret('value', {'ENV_VAR': 'var'}))

  def testValidTypes(self):
    check = recipe_api.BoundProperty.legal_name

    for test, result, is_param_name in (
        ('', False, False),
        ('.', False, False),
        ('foo', True, False),
        ('weird.param.name', True, False),
        ('weird.param.name', False, True),
        ('rietveld_url', True, False),):
      self.assertEqual(
          check(test, is_param_name=is_param_name), result,
          "name {} should be {}. is_param_name={}".format(
              test, result, is_param_name))

  def testParamName(self):
    """
    Tests setting a param name correctly carries through to a bound property.
    """
    prop = recipe_api.Property(param_name='b')
    bound = prop.bind('a', RECIPE_PROPERTY, 'fake_repo::fake_recipe')

    self.assertEqual('b', bound.param_name)

  def testParamNameDotted(self):
    """
    Tests setting a param name correctly carries through to a bound property.
    """
    prop = recipe_api.Property(param_name='good_name')
    bound = prop.bind('bad.name-time', RECIPE_PROPERTY,
                      'fake_repo::fake_recipe')

    self.assertEqual('good_name', bound.param_name)

  def testModuleName(self):
    """
    Tests declaring $repo_name/module properties.
    """
    prop = recipe_api.Property(param_name='foo')
    prop.bind('$fake_repo/fake_module', MODULE_PROPERTY,
              'fake_repo::fake_module')

    with self.assertRaises(ValueError):
      prop.bind('$fake_repo/wrong_module', MODULE_PROPERTY,
                'fake_repo::fake_module')

    with self.assertRaises(ValueError):
      prop.bind('$fake_repo/fake_module', RECIPE_PROPERTY,
                'fake_repo::fake_module:example')


if __name__ == '__main__':
  test_env.main()
