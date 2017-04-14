#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import subprocess
import sys
import unittest

import repo_test_util


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

    # Trying to override just the b repo should fail (conflicting revisions
    # of the a repo).
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      self.train_recipes(repos['c'], overrides=[('b', repos['b1']['root'])])
    # TODO(phajdan.jr): assert on full message after making exception printable.
    self.assertIn('InconsistentDependencyGraphError', cm.exception.output)

    # The solution is to also override the a repo to make it clear what revision
    # should be used.
    self.train_recipes(
        repos['c'],
        overrides=[('b', repos['b1']['root']), ('a', repos['a']['root'])])


if __name__ == '__main__':
  sys.exit(unittest.main())
