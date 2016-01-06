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
  def _test_cmd(self, repo, cmd, asserts, retcode=0):
    subp = subprocess.Popen(
        repo.recipes_cmd + cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    stdout, stderr = subp.communicate()
    if asserts:
      asserts(stdout, stderr)
    self.assertEqual(subp.returncode, retcode)

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

  def test_syntax_error(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', """
DEPS = [ (sic)
""")

      def assert_syntaxerror(stdout, stderr):
        self.assertRegexpMatches(stdout + stderr, r'SyntaxError')

      self._test_cmd(repo, ['simulation_test', 'test', 'foo'],
          asserts=assert_syntaxerror, retcode=1)
      self._test_cmd(repo, ['simulation_test', 'train', 'foo'],
          asserts=assert_syntaxerror, retcode=1)
      self._test_cmd(repo, ['run', 'foo'],
          asserts=assert_syntaxerror, retcode=1)

  def test_missing_path(self):
    with RecipeRepo() as repo:
      repo.make_recipe('missing_path', """
DEPS = ['recipe_engine/step', 'recipe_engine/path']

def RunSteps(api):
  api.step('do it, joe', ['echo', 'JOE'], cwd=api.path['bippityboppityboo'])

def GenTests(api):
  yield api.test('basic')
""")
      def assert_keyerror(stdout, stderr):
        self.assertRegexpMatches(
            stdout + stderr, r"KeyError: 'Unknown path: bippityboppityboo'")

      self._test_cmd(repo, ['simulation_test', 'train', 'missing_path'],
          asserts=assert_keyerror, retcode=1)
      self._test_cmd(repo, ['simulation_test', 'test', 'missing_path'],
          asserts=assert_keyerror, retcode=1)
      self._test_cmd(repo, ['run', 'missing_path'],
          asserts=assert_keyerror, retcode=255)

  def test_engine_failure(self):
    with RecipeRepo() as repo:
      repo.make_recipe('print_step_error', """
DEPS = ['recipe_engine/step']

from recipe_engine import step_runner

def bad_print_step(self, step_stream, step, env):
  raise Exception("Buh buh buh buh bad to the bone")

def RunSteps(api):
  step_runner.SubprocessStepRunner._print_step = bad_print_step
  try:
    api.step('Be good', ['echo', 'Sunshine, lollipops, and rainbows'])
  finally:
    api.step.active_result.presentation.status = 'WARNING'
""")
      self._test_cmd(repo, ['run', 'print_step_error'],
        asserts=lambda stdout, stderr: self.assertRegexpMatches(
            stdout + stderr,
            r'(?s)Recipe engine bug.*Buh buh buh buh bad to the bone'),
        retcode=2)

  def test_unconsumed_assertion(self):
    # There was a regression where unconsumed exceptions would not be detected
    # if the exception was AssertionError.

    with RecipeRepo() as repo:
      repo.make_recipe('unconsumed_assertion', """
DEPS = []

def RunSteps(api):
  pass

def GenTests(api):
  yield api.test('basic') + api.expect_exception('AssertionError')
""")
      self._test_cmd(repo, ['simulation_test', 'train', 'unconsumed_assertion'],
        asserts=lambda stdout, stderr: self.assertRegexpMatches(
            stdout + stderr, 'Unconsumed'),
        retcode=1)

if __name__ == '__main__':
  unittest.main()
