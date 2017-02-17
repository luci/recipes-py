#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import subprocess
import sys
import unittest

import repo_test_util


class TestSimulation(repo_test_util.RepoTest):
  def test_basic(self):
    repos = self.repo_setup({
        'a': [],
    })

    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})

    # Training the recipes should work.
    self.train_recipes(repos['a'])

  def test_no_coverage(self):
    repos = self.repo_setup({
        'a': [],
    })

    with self.assertRaises(subprocess.CalledProcessError) as cm:
      self.update_recipe_module(
          repos['a'], 'a_module', {'foo': ['bar']}, generate_example=False)
      self.train_recipes(repos['a'])
    self.assertIn(
        'Exception: The following modules lack test coverage: a_module',
        cm.exception.output)

  def test_no_coverage_whitelisted(self):
    repos = self.repo_setup({
        'a': [],
    })

    self.update_recipe_module(
        repos['a'], 'a_module', {'foo': ['bar']}, generate_example=False,
        disable_strict_coverage=True)

    # Training the recipes should work.
    self.train_recipes(repos['a'])

  def test_incomplete_coverage(self):
    repos = self.repo_setup({
        'a': [],
    })

    with self.assertRaises(subprocess.CalledProcessError) as cm:
      self.update_recipe_module(
          repos['a'], 'a_module', {'foo': ['bar'], 'baz': ['gazonk']},
          generate_example=['foo'])
      self.train_recipes(repos['a'])
    self.assertRegexpMatches(
        cm.exception.output,
        r'FATAL: Test coverage \d+% is not the required 100% threshold')

  def test_incomplete_coverage_whitelisted(self):
    repos = self.repo_setup({
        'a': [],
    })

    # Even with disabled strict coverage, regular coverage (100%)
    # should still be enforced.
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      self.update_recipe_module(
          repos['a'], 'a_module', {'foo': ['bar'], 'baz': ['gazonk']},
          generate_example=['foo'], disable_strict_coverage=True)
      self.train_recipes(repos['a'])
    self.assertRegexpMatches(
        cm.exception.output,
        r'FATAL: Test coverage \d+% is not the required 100% threshold')

  def test_recipe_coverage_strict(self):
    repos = self.repo_setup({
        'a': [],
    })

    self.update_recipe_module(
        repos['a'], 'a_module', {'foo': ['bar'], 'baz': ['gazonk']})
    self.update_recipe(
        repos['a'], 'a_recipe', ['a/a_module'],
        [('a_module', 'foo'), ('a_module', 'baz')])

    # Verify that strict coverage is enforced: even though the recipe
    # would otherwise cover entire module, we want module's tests
    # to be self-contained, and cover 100% of the module's code.
    with self.assertRaises(subprocess.CalledProcessError) as cm:
      self.update_recipe_module(
          repos['a'], 'a_module', {'foo': ['bar'], 'baz': ['gazonk']},
          generate_example=['foo'])
      self.train_recipes(repos['a'])
    self.assertRegexpMatches(
        cm.exception.output,
        r'FATAL: Test coverage \d+% is not the required 100% threshold')

  def test_recipe_coverage_strict_whitelisted(self):
    repos = self.repo_setup({
        'a': [],
    })

    self.update_recipe_module(
        repos['a'], 'a_module', {'foo': ['bar'], 'baz': ['gazonk']})
    self.update_recipe(
        repos['a'], 'a_recipe', ['a/a_module'],
        [('a_module', 'foo'), ('a_module', 'baz')])
    self.update_recipe_module(
        repos['a'], 'a_module', {'foo': ['bar'], 'baz': ['gazonk']},
        generate_example=['foo'], disable_strict_coverage=True)

    # Training the recipes should work.
    self.train_recipes(repos['a'])


if __name__ == '__main__':
  sys.exit(unittest.main())
