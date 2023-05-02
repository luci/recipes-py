#!/usr/bin/env vpython3
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import test_env


class TestSimulation(test_env.RecipeEngineUnitTest):
  def test_basic(self):
    deps = self.FakeRecipeDeps()
    with deps.main_repo.write_module('modname') as mod:
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])
      ''')
    with deps.main_repo.write_file('recipe_modules/modname/tests/r.py') as mod:
      mod.write('''
        DEPS = ['modname']
        def RunSteps(api):
          api.modname.some_function()
        def GenTests(api):
          yield api.test('basic')
      ''')

    # Training the recipes should work.
    output, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 0, 'failed train with output:\n' + output)

  def test_no_coverage(self):
    deps = self.FakeRecipeDeps()
    with deps.main_repo.write_module('modname') as mod:
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])
      ''')

    # Now there's nothing which uses the module, so we should get insufficient
    # test coverage.
    output, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)
    self.assertIn(
        'The following modules lack any form of test coverage:\n   modname',
        output)

  def test_no_coverage_whitelisted(self):
    deps = self.FakeRecipeDeps()

    with deps.main_repo.write_module('modname') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])
      ''')

    # Unrelated recipe; otherwise NO tests run and so coverage is ignored.
    with deps.main_repo.write_recipe('unrelated'):
      pass

    output, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)
    self.assertIn('FATAL: Insufficient total coverage', output)

  def test_incomplete_coverage(self):
    deps = self.FakeRecipeDeps()

    with deps.main_repo.write_module('modname') as mod:
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])

        def other_function(self):
          self.m.step('do something else', ['echo', 'nop'])
      ''')

    with deps.main_repo.write_recipe('modname', 'examples/full') as recipe:
      recipe.DEPS = ['modname']
      recipe.RunSteps.write('''
        api.modname.some_function()
        # omit call to other_function()
      ''')

    output, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)
    self.assertIn('FATAL: Insufficient total coverage', output)

  def test_incomplete_coverage_whitelisted(self):
    deps = self.FakeRecipeDeps()

    # Even with disabled strict coverage, regular coverage (100%)
    # should still be enforced.
    with deps.main_repo.write_module('modname') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])

        def other_function(self):
          self.m.step('do something else', ['echo', 'nop'])
      ''')

    with deps.main_repo.write_recipe('modname', 'examples/full') as recipe:
      recipe.DEPS = ['modname']
      recipe.RunSteps.write('''
        api.modname.some_function()
        # omit call to other_function()
      ''')

    output, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)
    self.assertIn('FATAL: Insufficient total coverage', output)

  def test_recipe_coverage_strict(self):
    deps = self.FakeRecipeDeps()

    with deps.main_repo.write_module('modname') as mod:
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])

        def other_function(self):
          self.m.step('do something else', ['echo', 'nop'])
      ''')

    # Verify that strict coverage is enforced: even though the recipe would
    # otherwise cover entire module, we want module's tests to be
    # self-contained, and cover 100% of the module's code.
    with deps.main_repo.write_recipe('my_recipe') as recipe:
      recipe.DEPS = ['modname']
      recipe.RunSteps.write('''
        api.modname.some_function()
        api.modname.other_function()
      ''')
      recipe.GenTests.write('''
        yield api.test("basic")
      ''')

    output, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 1)
    self.assertIn('FATAL: Insufficient total coverage', output)

  def test_recipe_coverage_strict_whitelisted(self):
    deps = self.FakeRecipeDeps()

    with deps.main_repo.write_module('modname') as mod:
      mod.DISABLE_STRICT_COVERAGE = True
      mod.api.write('''
        def some_function(self):
          self.m.step('do something', ['echo', 'hey'])

        def other_function(self):
          self.m.step('do something else', ['echo', 'nop'])
      ''')

    with deps.main_repo.write_recipe('my_recipe') as recipe:
      recipe.DEPS = ['modname']
      recipe.RunSteps.write('''
        api.modname.some_function()
        api.modname.other_function()
      ''')
      recipe.GenTests.write('''
        yield api.test("basic")
      ''')

    # Training the recipes should work.
    _, retcode = deps.main_repo.recipes_py('test', 'train')
    self.assertEqual(retcode, 0)


if __name__ == '__main__':
  test_env.main()
