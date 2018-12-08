#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import shutil
import subprocess
import sys
import unittest

import repo_test_util

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RunTest(repo_test_util.RepoTest):
  def test_run(self):
    repos = self.repo_setup({'a': []})
    self.update_recipe_module(repos['a'], 'mod', {'foo': []})
    self.update_recipe(repos['a'], 'a_recipe', ['mod'], [('mod', 'foo')])
    try:
      subprocess.check_output([
        sys.executable, os.path.join(repos['a']['root'], 'recipes.py'),
        '-v', '-v', 'run', 'a_recipe',
      ], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as ex:
      print >> sys.stdout, ex.message, ex.output
      raise

  def test_run_no_git(self):
    repos = self.repo_setup({'a': []})
    self.update_recipe_module(repos['a'], 'mod', {'foo': []})
    self.update_recipe(repos['a'], 'a_recipe', ['mod'], [('mod', 'foo')])
    shutil.rmtree(os.path.join(repos['a']['root'], '.git'))
    shutil.copy(os.path.join(ROOT_DIR, 'recipes.py'),
                os.path.join(repos['a']['root'], 'recipes.py'))
    try:
      subprocess.check_output([
        sys.executable, os.path.join(repos['a']['root'], 'recipes.py'),
        '-v', '-v',
        '--package', os.path.join(repos['a']['root'], 'infra', 'config',
                                  'recipes.cfg'),
        'run', 'a_recipe',
      ], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as ex:
      print >> sys.stdout, ex.message, ex.output
      raise


if __name__ == '__main__':
  sys.exit(unittest.main())

