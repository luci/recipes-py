#!/usr/bin/env vpython
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests for the 'analyze' command."""

import json
import os
import subprocess
import sys

import mock

import test_env

from recipe_engine.internal.commands.analyze import cmd as analyze
from PB.recipe_engine.analyze import Input, Output


class AnalyzeTest(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super(AnalyzeTest, self).setUp()
    self.git_attr_patcher = mock.patch(
        'recipe_engine.internal.commands.analyze.cmd.get_git_attribute_files',
        side_effect=self.git_attr)
    self.git_attr_patcher.start()
    self.git_attr_files = []

  def tearDown(self):
    self.git_attr_patcher.stop()
    self.git_attr_files = None
    super(AnalyzeTest, self).tearDown()

  def git_attr(self, repo_root):
    return [os.path.join(repo_root, path) for path in self.git_attr_files]

  def _run(self, recipe_deps, git_attr_files, in_data):
    self.git_attr_files = git_attr_files
    result = analyze.analyze(recipe_deps, in_data)
    result.recipes.sort()
    result.invalid_recipes.sort()

    return result

  def testInvalidRecipe(self):
    result = self._run(
      self.MockRecipeDeps(),
      git_attr_files=[], in_data=Input(
        files=['foo.py'],
        recipes=['run_test.py'],
      ))
    self.assertEqual(result, Output(
      error='Some input recipes were invalid',
      invalid_recipes=['run_test.py'],
    ))

  def testUnusedFiles(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=Input(
          files=['some_random_file'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, Output())

  def testGitAttrs(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {
          'run_test': ['foo_module'],
          'other_thing': ['foo_module'],
          'last_recipe': ['foo_module'],
        }
      ), git_attr_files=['foo.py'], in_data=Input(
          files=['foo.py'],
          recipes=['run_test', 'other_thing', 'last_recipe'],
      ))
    self.assertEqual(result, Output(
        recipes=sorted(['run_test', 'other_thing', 'last_recipe']),
    ))

  def testSimple(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, Output(
      recipes=['run_test'],
    ))

  def testAbsPath(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=Input(
          files=['/MAIN_ROOT/recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, Output(
      recipes=['run_test'],
    ))

  def testRecipeFile(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=Input(
          files=['recipes/run_test.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, Output(
      recipes=['run_test'],
    ))

  def testDependency(self):
    result = self._run(self.MockRecipeDeps(
        {
          'foo_module': ['bar_module'],
          'bar_module': [],
        },
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=Input(
          files=['recipe_modules/bar_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, Output(
      recipes=['run_test'],
    ))

  def testTwoRecipes(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {
          'run_test': ['foo_module'],
          'run_other_test': ['foo_module'],
        }
      ), git_attr_files=[], in_data=Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test', 'run_other_test'],
      ))
    self.assertEqual(result, Output(
      recipes=sorted(['run_test', 'run_other_test']),
    ))

  def testTwoRecipesOnlyOne(self):
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {
          'run_test': ['foo_module'],
          'run_other_test': [],
        }
      ), git_attr_files=[], in_data=Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test', 'run_other_test'],
      ))
    self.assertEqual(result, Output(
      recipes=['run_test'],
    ))

  def testOneRecipeTwoModules(self):
    result = self._run(self.MockRecipeDeps(
        {
          'foo_module': [],
          'bar_module': [],
        },
        {
          'run_test': ['foo_module', 'bar_module'],
        }
      ), git_attr_files=[], in_data=Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, Output(
      recipes=['run_test'],
    ))

  def testSimilarModuleChanged(self):
    result = self._run(self.MockRecipeDeps(
        {
          'foo': [],
          'foo_bar': [],
        },
        {
          'recipe': ['foo'],
        }
      ), git_attr_files=[], in_data=Input(
          files=['recipe_modules/foo_bar/api.py'],
          recipes=['recipe'],
      ))
    self.assertEqual(result, Output())


class AnalyzeSmokeTest(test_env.RecipeEngineUnitTest):
  """Small smoke test that makes sure analyze works.
  """

  def _run(self, indata):
    infile = self.tempfile()
    with open(infile, 'w') as f:
      json.dump(indata, f)

    outfile = self.tempfile()
    exit_code = subprocess.call([
      sys.executable, os.path.join(test_env.ROOT_DIR, 'recipes.py'),
      'analyze', infile, outfile])
    with open(outfile) as f:
      return exit_code, json.load(f)

  def testInvalidRecipe(self):
    exit_code, outdata = self._run({
      'files': ['recipe_modules/step/api.py'],
      'recipes': ['engine_tests/unicooooooode'],
    })
    self.assertDictEqual(outdata, {
      'error': 'Some input recipes were invalid',
      'invalidRecipes': ['engine_tests/unicooooooode'],
      'recipes': [],
    })
    self.assertEqual(exit_code, 1)

  def testNotChanged(self):
    # The test here assumes that unicode recipe has no direct or indirect
    # dependencies on tricium recipe_module. If you invalidate this assumption,
    # you should change this test.
    exit_code, outdata = self._run({
      'files': ['recipe_modules/tricium/api.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': [],
    })
    self.assertEqual(exit_code, 0)

  def testGitAttrs(self):
    exit_code, outdata = self._run({
      'files': ['.vpython'],  # vpython is included via .gitattributes
      'recipes': [
        'engine_tests/unicode',
        'engine_tests/whitelist_steps',
      ],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      # List should be safe to not wrap with a call to sorted, since
      # proto repeated fields are ordered, so everything should be
      # analyzed in the same order every time.
      'recipes': [
        'engine_tests/whitelist_steps',
        'engine_tests/unicode',
      ],
    })
    self.assertEqual(exit_code, 0)

  def testRecipeChanged(self):
    exit_code, outdata = self._run({
      'files': ['recipes/engine_tests/unicode.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)

  def testRecipeResourceChanged(self):
    exit_code, outdata = self._run({
      'files': ['recipes/engine_tests/unicode.resources/helper.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)

  def testRecipeChangedAbsPath(self):
    exit_code, outdata = self._run({
            'files': [os.path.join(
                test_env.ROOT_DIR, 'recipes', 'engine_tests', 'unicode.py')],
            'recipes': ['engine_tests/unicode'],
        })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)

  def testModuleChanged(self):
    exit_code, outdata = self._run({
      'files': ['recipe_modules/step/api.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)


if __name__ == '__main__':
  test_env.main()
