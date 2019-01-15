#!/usr/bin/env vpython
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tests for the 'analyze' command."""

import collections
import json
import os
import re
import subprocess
import tempfile
import time
import unittest

import mock

import test_env


from recipe_engine import analyze, analyze_pb2
import recipe_engine.loader

class MockPackage(object):
  def __init__(self, name):
    self.name = name
    self.repo_root = '/' + os.path.join('', 'stuff', name)

class MockUniverse(object):
  def __init__(self, root_package, modules, recipes):
    self.modules = modules
    self.recipes = recipes
    self.package_deps = MockPackageDeps(root_package)

  def load(self, package, name):
    return MockModule(package.name, name, self)

  def loop_over_recipe_modules(self):
    return [(MockPackage(package), module)
            for package, module in self.modules.keys()]

class MockPackageDeps(object):
  def __init__(self, root_package):
    self.root_package = MockPackage(root_package)

  def get_package(self, pkg):
    return MockPackage(pkg)

class MockUniverseView(object):
  def __init__(self, universe, package):
    self.universe = universe
    self.package = package

  def load_recipe(self, name):
    return MockRecipe(self.package.name, name, self.universe)

  def loop_over_recipes(self):
    return [(None, name) for (package, name) in self.universe.recipes.keys()
            if package == self.package.name]

class MockPath(object):
  def __init__(self, val):
    self.base = self
    self.val = val

  def resolve(self, _):
    return self.val

class MockModule(object):
  def __init__(self, pkg_name, name, universe):
    self.NAME = name
    self.UNIQUE_NAME = '%s/%s' % (pkg_name, name)
    self.LOADED_DEPS = {
        i: MockModule(pkg_name, dep, universe)
        for (i, dep) in enumerate(universe.modules[(pkg_name, name)])
    }
    self.MODULE_DIRECTORY = MockPath(os.path.join(
        universe.package_deps.root_package.repo_root, 'recipe_modules', name))

class MockRecipe(object):
  def __init__(self, pkg_name, name, universe):
    self.LOADED_DEPS = {i: MockModule(
        pkg_name, dep, universe) for (i, dep) in enumerate(
            universe.recipes[(pkg_name, name)])}
    self.path = (
        os.path.join(
            universe.package_deps.root_package.repo_root, 'recipes', name)
        + '.py')

class AnalyzeTest(unittest.TestCase):
  def setUp(self):
    self.git_attr_patcher = mock.patch(
        'recipe_engine.analyze.get_git_attribute_files',
        side_effect=self.git_attr)
    self.git_attr_patcher.start()
    self.git_attr_files = []
    self.universe_view_patcher = mock.patch(
        'recipe_engine.loader.UniverseView',
        side_effect=MockUniverseView)
    self.universe_view_patcher.start()

  def tearDown(self):
    self.git_attr_patcher.stop()
    self.git_attr_files = None

  def git_attr(self, repo_root):
    return [os.path.join(repo_root, path) for path in self.git_attr_files]

  def _run(self, universe, git_attr_files, in_data):
    self.git_attr_files = git_attr_files
    result = analyze.analyze(universe, in_data)
    result.recipes.sort()
    result.invalid_recipes.sort()

    return result

  def testInvalidRecipe(self):
    result = self._run(MockUniverse(
        'root_package', modules={}, recipes={}
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['foo.py'],
          recipes=['run_test.py'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      error='Some input recipes were invalid',
      invalid_recipes=['run_test.py'],
    ))

  def testUnusedFiles(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['some_random_file'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output())

  def testGitAttrs(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
          ('root_package', 'other_thing'): ['foo_module'],
          ('root_package', 'last_recipe'): ['foo_module'],
        }
      ), git_attr_files=['foo.py'], in_data=analyze_pb2.Input(
          files=['foo.py'],
          recipes=['run_test', 'other_thing', 'last_recipe'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
        recipes=sorted(['run_test', 'other_thing', 'last_recipe']),
    ))

  def testSimple(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=['run_test'],
    ))

  def testAbsPath(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=['run_test'],
    ))

  def testRecipeFile(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipes/run_test.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=['run_test'],
    ))

  def testDependency(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): ['bar_module'],
          ('root_package', 'bar_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipe_modules/bar_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=['run_test'],
    ))

  def testTwoRecipes(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
          ('root_package', 'run_other_test'): ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test', 'run_other_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=sorted(['run_test', 'run_other_test']),
    ))

  def testTwoRecipesOnlyOne(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module'],
          ('root_package', 'run_other_test'): [],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test', 'run_other_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=['run_test'],
    ))

  def testOneRecipeTwoModules(self):
    result = self._run(MockUniverse(
        'root_package', modules={
          ('root_package', 'foo_module'): [],
          ('root_package', 'bar_module'): [],
        }, recipes={
          ('root_package', 'run_test'): ['foo_module', 'bar_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb2.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb2.Output(
      recipes=['run_test'],
    ))

if __name__ == '__main__':
  unittest.main()

