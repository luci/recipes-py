#!/usr/bin/env vpython3
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import test_env

from recipe_engine import recipe_api, config


RECIPE_PROPERTY = recipe_api.BoundProperty.RECIPE_PROPERTY
MODULE_PROPERTY = recipe_api.BoundProperty.MODULE_PROPERTY


def make_prop(**kwargs):
  name = kwargs.pop('name', 'dumb_name')
  return recipe_api.Property(**kwargs).bind(
    name, RECIPE_PROPERTY, 'fake_repo::fake_recipe')


class TestProperties(test_env.RecipeEngineUnitTest):
  def testDefault(self):
    """Tests the default option of properties."""
    for val in (1, {}, 'test', None):
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
    for value in (1, 'hi', [3, 'test']):
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
    # Explicit values override the environment.
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


class TestProtoProperties(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super(TestProtoProperties, self).setUp()
    self.deps = self.FakeRecipeDeps()

    main = self.deps.main_repo
    with main.write_file('recipe_proto/proto_props/props.proto') as proto:
      proto.write('''
        syntax = "proto3";
        message Props {
          string best_prop = 1;
          int32 worst_prop = 2;
        }
        message ModProps {
          string mod_prop = 1;
        }
        message EnvProps {
          string STR_ENVVAR = 1;
          int32  NUM_ENVVAR = 2;
        }
      ''')

  def testRecipeProperties(self):
    main = self.deps.main_repo

    with main.write_recipe('recipe') as recipe:
      recipe.imports = ['from PB.proto_props import props']
      recipe.DEPS += ['recipe_engine/properties']
      recipe.PROPERTIES = 'props.Props'
      recipe.ENV_PROPERTIES = 'props.EnvProps'
      recipe.RunSteps_args += ['props', 'env_props']
      recipe.RunSteps.write('''
        api.step('dump', ['echo', '[ normal prop:', props.best_prop, ']'])
        api.step('dump', ['echo', '[ env prop:', env_props.STR_ENVVAR, ']'])
      ''')

    output, retcode = main.recipes_py(
        'run', 'recipe', 'best_prop="best property"', env={
          'STR_ENVVAR': 'coolio',
        })
    self.assertEqual(retcode, 0, output)
    self.assertIn('[ normal prop: best property ]', output)
    self.assertIn('[ env prop: coolio ]', output)

  def testModuleProperties(self):
    main = self.deps.main_repo

    with main.write_module('modname') as mod:
      mod.imports = ['from PB.proto_props import props']
      mod.PROPERTIES = 'props.ModProps'
      mod.GLOBAL_PROPERTIES = 'props.Props'
      mod.ENV_PROPERTIES = 'props.EnvProps'
      mod.api.write('''
        def __init__(self, props, global_props, env_props, **kwargs):
          super(ModnameApi, self).__init__(**kwargs)
          self.value = global_props.best_prop
          self.mod_value = props.mod_prop
          self.env_value_str = env_props.STR_ENVVAR
          self.env_value_num = env_props.NUM_ENVVAR
      ''')

    with main.write_recipe('recipe') as recipe:
      recipe.DEPS += ['modname']
      recipe.RunSteps.write('''
        api.step('dump global', ['echo', '[ global:', api.modname.value, ']'])
        api.step('dump mod', ['echo', '[ mod:', api.modname.mod_value, ']'])
        api.step('dump env str', ['echo', '[ env str:', api.modname.env_value_str, ']'])
        api.step('dump env num', ['echo', '[ env num:', api.modname.env_value_num, ']'])
      ''')

    output, retcode = main.recipes_py(
        'run', 'recipe', 'best_prop="best property"',
        '$main/modname={"mod_prop": "mod property"}',
        env={
          'STR_ENVVAR': 'env property',
          'NUM_ENVVAR': '9000',
        })
    self.assertEqual(retcode, 0, output)
    self.assertIn('[ global: best property ]', output)
    self.assertIn('[ mod: mod property ]', output)
    self.assertIn('[ env str: env property ]', output)
    self.assertIn('[ env num: 9000 ]', output)

  def testBadPropertyType(self):
    main = self.deps.main_repo

    with main.write_recipe('recipe') as recipe:
      recipe.imports = ['from PB.proto_props import props']
      recipe.PROPERTIES = 'props.Props'
      recipe.RunSteps_args += ['properties']

    output, retcode = main.recipes_py('run', 'recipe',
                                      'worst_prop="invalid value"')
    self.assertNotEqual(retcode, 0, output)
    self.assertRegexpMatches(output, r'ParseError.*worst_prop.*invalid value')


if __name__ == '__main__':
  test_env.main()
