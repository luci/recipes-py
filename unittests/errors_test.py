#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class RecipeRepo(object):
  def __init__(self):
    self._root = tempfile.mkdtemp()
    os.makedirs(os.path.join(self._root, 'infra', 'config'))
    self._recipes_cfg = os.path.join(
        self._root, 'infra', 'config', 'recipes.cfg')
    with open(self._recipes_cfg, 'w') as fh:
      fh.write("""
api_version: 1
project_id: "testproj"
deps {
  project_id: "recipe_engine"
  url: "%s"
  branch: "master"
  revision: "HEAD"
}
""" % ROOT_DIR)
    self._recipes_dir = os.path.join(self._root, 'recipes')
    os.mkdir(self._recipes_dir)
    self._modules_dir = os.path.join(self._root, 'recipe_modules')
    os.mkdir(self._modules_dir)

  def make_recipe(self, recipe, contents):
    with open(os.path.join(self._recipes_dir, '%s.py' % recipe), 'w') as fh:
      fh.write(contents)

  def make_module(self, name, init_contents, api_contents):
    module_root = os.path.join(self._modules_dir, name)
    os.mkdir(module_root)
    with open(os.path.join(module_root, '__init__.py'), 'w') as fh:
      fh.write(init_contents)
    with open(os.path.join(module_root, 'api.py'), 'w') as fh:
      fh.write(api_contents)

  @property
  def recipes_cmd(self):
    return [
        os.path.join(ROOT_DIR, 'recipes.py'),
        '--package', self._recipes_cfg,
        '-O', 'recipe_engine=%s' % ROOT_DIR]

  def __enter__(self):
    return self

  def __exit__(self, *_):
    shutil.rmtree(self._root)

class ErrorsTest(unittest.TestCase):
  def test_missing_dependency(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', """
DEPS = ['aint_no_thang']
""")
      subp = subprocess.Popen(
          repo.recipes_cmd + ['run', 'foo'],
          stdout=subprocess.PIPE)
      stdout, _ = subp.communicate()
      self.assertRegexpMatches(stdout,
        r'aint_no_thang does not exist[^\n]*while loading recipe foo')
      self.assertEqual(subp.returncode, 2)

  def test_missing_module_dependency(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', 'DEPS = ["le_module"]')
      repo.make_module('le_module', 'DEPS = ["love"]', '')
      subp = subprocess.Popen(
          repo.recipes_cmd + ['run', 'foo'],
          stdout=subprocess.PIPE)
      stdout, _ = subp.communicate()
      self.assertRegexpMatches(stdout,
        r'love does not exist[^\n]*'
        r'while loading recipe module \S*le_module[^\n]*'
        r'while loading recipe foo')
      self.assertEqual(subp.returncode, 2)

  def test_no_such_recipe(self):
    with RecipeRepo() as repo:
      subp = subprocess.Popen(
          repo.recipes_cmd + ['run', 'nooope'],
          stdout=subprocess.PIPE)
      stdout, _ = subp.communicate()
      self.assertRegexpMatches(stdout, r'No such recipe: nooope')
      self.assertEqual(subp.returncode, 2)

if __name__ == '__main__':
  unittest.main()
