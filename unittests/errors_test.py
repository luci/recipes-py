#!/usr/bin/env vpython
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os
import shutil
import subprocess
import tempfile
import unittest

import repo_test_util
from repo_test_util import ROOT_DIR


class RecipeRepo(object):
  def __init__(self, recipes_path=''):
    self._root = tempfile.mkdtemp()
    os.makedirs(os.path.join(self._root, 'infra', 'config'))
    self._recipes_cfg = os.path.join(
        self._root, 'infra', 'config', 'recipes.cfg')
    with open(self._recipes_cfg, 'w') as fh:
      json.dump({
        'api_version': 2,
        'project_id': 'testproj',
        'recipes_path': recipes_path,
        'deps': {
          'recipe_engine':{
            'url': ROOT_DIR,
            'branch': 'master',
            'revision': 'HEAD'
          }
        }
      }, fh)
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
  def _test_cmd(self, repo, cmd, asserts=None, retcode=0, engine_args=None):
    engine_args = engine_args or []
    if cmd[0] == 'run':
      _, path = tempfile.mkstemp('result_pb')
      cmd = [cmd[0]] + ['--output-result-json', path] + cmd[1:]

    try:
      subp = subprocess.Popen(
          repo.recipes_cmd + engine_args + cmd,
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE)
      stdout, stderr = subp.communicate()

      if asserts:
        asserts(stdout, stderr)
      self.assertEqual(
          subp.returncode, retcode,
          '%d != %d.\nstdout:\n%s\nstderr:\n%s' % (
              subp.returncode, retcode, stdout, stderr))

      if cmd[0] == 'run':
        if not os.path.exists(path):
          return

        with open(path) as tf:
          raw = tf.read()
          data = None
          if raw:
            data = json.loads(raw)
        return data
    finally:
      if cmd[0] == 'run':
        if os.path.exists(path):
          os.unlink(path)

  def test_missing_dependency(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', """
DEPS = ['aint_no_thang']
""")
      subp = subprocess.Popen(
          repo.recipes_cmd + ['run', 'foo'],
          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      stdout, stderr = subp.communicate()
      self.assertRegexpMatches(stdout + stderr,
        r'No module named aint_no_thang', stdout + stderr)
      self.assertEqual(subp.returncode, 2)

  def test_missing_dependency_new(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', """
DEPS = ['aint_no_thang']
""")

      _, path = tempfile.mkstemp('args_pb')
      with open(path, 'w') as f:
        json.dump({
          'engine_flags': {
            'use_result_proto': True
          }
        }, f)

      try:
        def assert_nomodule(stdout, stderr):
          self.assertRegexpMatches(
              stdout + stderr, r'No module named aint_no_thang')

        self._test_cmd(
            repo, ['run', 'foo'], retcode=1, asserts=assert_nomodule,
            engine_args=['--operational-args-path', path])
      finally:
        if os.path.exists(path):
          os.unlink(path)

  def test_missing_module_dependency(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', 'DEPS = ["le_module"]')
      repo.make_module('le_module', 'DEPS = ["love"]', '')

      def assert_nomodule(stdout, stderr):
        self.assertRegexpMatches(stdout + stderr, r'No module named love')

      self._test_cmd(
          repo, ['run', 'foo'], retcode=2, asserts=assert_nomodule)

  def test_missing_module_dependency_new(self):
    with RecipeRepo() as repo:
      _, path = tempfile.mkstemp('args_pb')
      with open(path, 'w') as f:
        json.dump({
          'engine_flags': {
            'use_result_proto': True
          }
        }, f)

      try:
        repo.make_recipe('foo', 'DEPS = ["le_module"]')
        repo.make_module('le_module', 'DEPS = ["love"]', '')

        def assert_nomodule(stdout, stderr):
          self.assertRegexpMatches(stdout + stderr, r'No module named love')

        self._test_cmd(
            repo, ['run', 'foo'], retcode=1, asserts=assert_nomodule,
            engine_args=['--operational-args-path', path])
      finally:
        if os.path.exists(path):
          os.unlink(path)

  def test_no_such_recipe(self):
    with RecipeRepo() as repo:
      subp = subprocess.Popen(
          repo.recipes_cmd + ['run', 'nooope'],
          stdout=subprocess.PIPE)
      stdout, _ = subp.communicate()
      self.assertRegexpMatches(stdout, r'No such recipe: nooope')
      self.assertEqual(subp.returncode, 2)

  def test_no_such_recipe_new(self):
    with RecipeRepo() as repo:
      _, path = tempfile.mkstemp('args_pb')
      with open(path, 'w') as f:
        json.dump({
          'engine_flags': {
            'use_result_proto': True
          }
        }, f)

      try:
        result = self._test_cmd(
            repo, ['run', 'nooope'], retcode=1,
            engine_args=['--operational-args-path', path])
        self.assertIsNotNone(result['failure']['exception'])
      finally:
        if os.path.exists(path):
          os.unlink(path)


  def test_syntax_error(self):
    with RecipeRepo() as repo:
      repo.make_recipe('foo', """
DEPS = [ (sic)
""")

      def assert_syntaxerror(stdout, stderr):
        self.assertRegexpMatches(stdout + stderr, r'SyntaxError')

      self._test_cmd(repo, ['test', 'run', '--filter', 'foo'],
          asserts=assert_syntaxerror, retcode=1)
      self._test_cmd(repo, ['test', 'train', '--filter', 'foo'],
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
            stdout + stderr, r"KeyError: 'Unknown path: bippityboppityboo'",
            stdout + stderr)

      self._test_cmd(repo, ['test', 'train', '--filter', 'missing_path'],
          asserts=assert_keyerror, retcode=1)
      self._test_cmd(repo, ['test', 'run', '--filter', 'missing_path'],
          asserts=assert_keyerror, retcode=1)
      self._test_cmd(repo, ['run', 'missing_path'],
          asserts=assert_keyerror, retcode=255)

  def test_missing_path_new(self):
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
            stdout + stderr, r"KeyError: 'Unknown path: bippityboppityboo'",
            stdout + stderr)

      _, path = tempfile.mkstemp('args_pb')
      with open(path, 'w') as f:
        json.dump({
          'engine_flags': {
            'use_result_proto': True
          }
        }, f)

      try:
        self._test_cmd(repo, ['test', 'train', '--filter', 'missing_path'],
            asserts=assert_keyerror, retcode=1,
            engine_args=['--operational-args-path', path])
        self._test_cmd(repo, ['test', 'run', '--filter', 'missing_path'],
            asserts=assert_keyerror, retcode=1,
            engine_args=['--operational-args-path', path])
        self._test_cmd(repo, ['run', 'missing_path'],
            asserts=assert_keyerror, retcode=1,
            engine_args=['--operational-args-path', path])
      finally:
        if os.path.exists(path):
          os.unlink(path)

  def test_engine_failure(self):
    with RecipeRepo() as repo:
      repo.make_recipe('print_step_error', """
DEPS = ['recipe_engine/step']

from recipe_engine import step_runner

def bad_print_step(self, step_stream, step, env):
  raise Exception("Buh buh buh buh bad to the bone")

def GenTests(api):
  pass

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

  def test_missing_method(self):
    with RecipeRepo() as repo:
      repo.make_recipe('no_gen_tests', """
def RunSteps(api):
  pass
""")
      repo.make_recipe('no_run_steps', """
def GenTests(api):
  pass
""")

      self._test_cmd(repo, ['run', 'no_gen_tests'],
        asserts=lambda stdout, stderr: self.assertRegexpMatches(
            stdout + stderr,
            r'(?s)misspelled GenTests'),
        retcode=2)

      self._test_cmd(repo, ['run', 'no_run_steps'],
        asserts=lambda stdout, stderr: self.assertRegexpMatches(
            stdout + stderr,
            r'(?s)misspelled RunSteps'),
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
      self._test_cmd(repo, ['test', 'train', '--filter', 'unconsumed_assertion'],
        asserts=lambda stdout, stderr: self.assertRegexpMatches(
            stdout + stderr, 'Unconsumed'),
        retcode=1)

  def test_run_recipe_help(self):
    with RecipeRepo(recipes_path='foo/bar') as repo:
      repo.make_recipe('do_nothing', """
DEPS = []
def RunSteps(api):
 pass
""")
      subp = subprocess.Popen(
                    repo.recipes_cmd + ['run', 'do_nothing'],
                              stdout=subprocess.PIPE)
      stdout, _ = subp.communicate()
      self.assertRegexpMatches(
          stdout, r'from the root of a \'testproj\' checkout')
      self.assertRegexpMatches(
          stdout, r'\./foo/bar/recipes\.py run .* do_nothing')





if __name__ == '__main__':
  unittest.main()
