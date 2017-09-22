#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import os
import subprocess
import sys
import unittest
import contextlib

import repo_test_util

@contextlib.contextmanager
def fake_git():
  fake_git_dir = os.path.join(repo_test_util.ROOT_DIR, 'unittests', 'fakegit')
  cur_path = os.environ['PATH']
  try:
    os.environ['PATH'] = os.pathsep.join([fake_git_dir, cur_path])
    yield
  finally:
    os.environ['PATH'] = cur_path

class TestOverride(repo_test_util.RepoTest):
  def test_simple(self):
    repos = self.repo_setup({
        'a': [],
        'a1': [],
        'b': ['a'],
    })

    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(repos['b'], 'a', a_c1['revision']))
    self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Training the recipes should work.
    self.train_recipes(repos['b'])

    # Using a no-op override should also work.
    self.train_recipes(repos['b'], overrides=[('a', repos['a']['root'])])

    # Using an override pointing to empty repo should fail.
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      self.train_recipes(repos['b'], overrides=[('a', repos['a1']['root'])])
    self.assertIn(
        'Exception: While generating results for \'b_recipe\': ImportError: '
        'No module named a_module',
        cm.exception.output)

  def test_bundle(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    }, remote_fake_engine=True)

    engine_override = ('recipe_engine', repo_test_util.ROOT_DIR)

    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']},
                                     overrides=[engine_override])

    self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(repos['b'], 'a', a_c1['revision']))
    self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')],
        overrides=[engine_override])

    with fake_git():
      # Training the recipes, overriding just 'a' should fail.
      with self.assertRaises(subprocess.CalledProcessError) as cm:
        self.train_recipes(repos['b'], overrides=[
          ('a', repos['a']['root']),
        ])
      self.assertIn('Git "init" failed', cm.exception.output)

      # But! Overriding the engine too should work.
      self.train_recipes(repos['b'], overrides=[
        ('a', repos['a']['root']),
        engine_override,
      ])

  def test_dependency_conflict(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
        'b1': ['a'],
        'c': ['a', 'b'],
    })

    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(repos['b'], 'a', a_c1['revision']))
    self.update_recipes_cfg(
        'b1', self.updated_package_spec_pb(repos['b1'], 'a', a_c1['revision']))

    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})
    b_c2_rev = self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(repos['b'], 'a', a_c2['revision']))

    c_spec = copy.deepcopy(self.get_package_spec(repos['c']).spec_pb)
    c_spec.deps['a'].revision = a_c2['revision']
    c_spec.deps['b'].revision = b_c2_rev
    self.update_recipes_cfg('c', c_spec)

    self.update_recipe(
        repos['c'], 'c_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Training the recipes should work.
    self.train_recipes(repos['c'])

    # Both overrides should also work, thanks to recursive override processing.
    self.train_recipes(
        repos['c'],
        overrides=[('b', repos['b1']['root'])])
    self.train_recipes(
        repos['c'],
        overrides=[('b', repos['b1']['root']), ('a', repos['a']['root'])])


if __name__ == '__main__':
  sys.exit(unittest.main())
