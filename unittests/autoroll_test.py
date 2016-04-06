#!/usr/bin/env python
# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import subprocess
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIRD_PARTY = os.path.join(ROOT_DIR, 'recipe_engine', 'third_party')
sys.path.insert(0, THIRD_PARTY)
sys.path.insert(0, ROOT_DIR)
from recipe_engine import package

import repo_test_util


class TestAutoroll(repo_test_util.RepoTest):
  def run_roll(self, repo):
    """Runs the autoroll command and returns JSON.
    Does not commit the resulting roll.
    """
    with repo_test_util.in_directory(repo['root']), \
        repo_test_util.temporary_file() as tempfile_path:
      subprocess.check_output([
          sys.executable, self._recipe_tool,
          '--package', os.path.join(
              repo['root'], 'infra', 'config', 'recipes.cfg'),
          'autoroll',
          '--output-json', tempfile_path
      ], stderr=subprocess.STDOUT)
      with open(tempfile_path) as f:
        return json.load(f)

  def test_empty(self):
    """Tests the scenario where there are no roll candidates.
    """
    repos = self.repo_setup({
        'a': [],
    })

    roll_result = self.run_roll(repos['a'])
    self.assertFalse(roll_result['success'])
    self.assertEquals([], roll_result['roll_details'])
    self.assertEquals([], roll_result['rejected_candidates_details'])

  def test_trivial(self):
    """Tests the simplest trivial (i.e. no expectation changes) roll scenario.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    b_package_spec = self.get_package_spec(repos['b'])

    # Create a new commit in the A repo.
    a_c1 = self.commit_in_repo(repos['a'], message='c1')

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author': a_c1['author_email'],
                    'message': a_c1['message'],
                    'repo_id': 'a',
                    'revision': a_c1['revision'],
                },
            ],
        },
        'spec': str(b_package_spec.dump()).replace(
            repos['a']['revision'], a_c1['revision']),
    }

    self.assertEqual(expected_picked_roll['commit_infos'],
                     roll_result['picked_roll_details']['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     roll_result['picked_roll_details']['spec'])
    self.assertEqual(
        0, roll_result['picked_roll_details']['recipes_simulation_test']['rc'])

  def test_nontrivial(self):
    """Tests the simplest nontrivial (i.e. expectation changes) roll scenario.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    b_package_spec = self.get_package_spec(repos['b'])

    # Set up a recipe in repo B depending on a module in repo A.
    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    b_c1 = self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in a way that's compatible,
    # but changes expectations.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author': a_c2['author_email'],
                    'message': a_c2['message'],
                    'repo_id': 'a',
                    'revision': a_c2['revision'],
                },
            ],
        },
        'spec': str(b_package_spec.dump()).replace(
            repos['a']['revision'], a_c2['revision']),
    }

    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(expected_picked_roll['commit_infos'],
                     picked_roll['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     picked_roll['spec'])
    self.assertEqual(
        1, picked_roll['recipes_simulation_test']['rc'])
    self.assertEqual(
        0, picked_roll['recipes_simulation_test_train']['rc'])

  def test_failure(self):
    """Tests the simplest scenario where an automated roll is not possible
    because of incompatible API changes.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })

    # Set up a recipe in repo B depending on a module in repo A.
    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    b_c1 = self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

    roll_result = self.run_roll(repos['b'])
    self.assertFalse(roll_result['success'])

  def test_jump_over_failure(self):
    """Tests whether the roller considers pulling more commits to make
    the roll succeed, when earlier ones have incompatible API changes
    fixed later.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    b_package_spec = self.get_package_spec(repos['b'])

    # Set up a recipe in repo B depending on a module in repo A.
    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    b_c1 = self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

    # Restore compatibility, but change expectations.
    a_c3 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author': a_c2['author_email'],
                    'message': a_c2['message'],
                    'repo_id': 'a',
                    'revision': a_c2['revision'],
                },
                {
                    'author': a_c3['author_email'],
                    'message': a_c3['message'],
                    'repo_id': 'a',
                    'revision': a_c3['revision'],
                },
            ],
        },
        'spec': str(b_package_spec.dump()).replace(
            repos['a']['revision'], a_c3['revision']),
    }

    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(expected_picked_roll['commit_infos'],
                     picked_roll['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     picked_roll['spec'])
    self.assertEqual(
        1, picked_roll['recipes_simulation_test']['rc'])
    self.assertEqual(
        0, picked_roll['recipes_simulation_test_train']['rc'])

  def test_pick_smallest_nontrivial_roll(self):
    """Test that with several nontrivial rolls possible, the minimal one
    is picked.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    b_package_spec = self.get_package_spec(repos['b'])

    # Set up a recipe in repo B depending on a module in repo A.
    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    b_c1 = self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

    # Restore compatibility, but change expectations.
    a_c3 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    # Create another change that would result in a nontrivial roll,
    # which should not be picked - nontrivial rolls should be minimal.
    a_c4 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bam']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author': a_c2['author_email'],
                    'message': a_c2['message'],
                    'repo_id': 'a',
                    'revision': a_c2['revision'],
                },
                {
                    'author': a_c3['author_email'],
                    'message': a_c3['message'],
                    'repo_id': 'a',
                    'revision': a_c3['revision'],
                },
            ],
        },
        'spec': str(b_package_spec.dump()).replace(
            repos['a']['revision'], a_c3['revision']),
    }

    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(expected_picked_roll['commit_infos'],
                     picked_roll['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     picked_roll['spec'])
    self.assertEqual(
        1, picked_roll['recipes_simulation_test']['rc'])
    self.assertEqual(
        0, picked_roll['recipes_simulation_test_train']['rc'])

  def test_pick_largest_trivial_roll(self):
    """Test that with several trivial rolls possible, the largest one is picked.
    This helps avoid noise with several rolls where one is sufficient,
    with no expectation changes.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    b_package_spec = self.get_package_spec(repos['b'])

    # Set up a recipe in repo B depending on a module in repo A.
    a_c1 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    b_c1 = self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

    # Restore compatibility, but change expectations.
    a_c3 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    # Create another change that would result in a nontrivial roll,
    # which should not be picked - nontrivial rolls should be minimal.
    a_c4 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bam']})

    # Introduce another commit which makes the roll trivial again.
    a_c5 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author': a_c2['author_email'],
                    'message': a_c2['message'],
                    'repo_id': 'a',
                    'revision': a_c2['revision'],
                },
                {
                    'author': a_c3['author_email'],
                    'message': a_c3['message'],
                    'repo_id': 'a',
                    'revision': a_c3['revision'],
                },
                {
                    'author': a_c4['author_email'],
                    'message': a_c4['message'],
                    'repo_id': 'a',
                    'revision': a_c4['revision'],
                },
                {
                    'author': a_c5['author_email'],
                    'message': a_c5['message'],
                    'repo_id': 'a',
                    'revision': a_c5['revision'],
                },
            ],
        },
        'spec': str(b_package_spec.dump()).replace(
            repos['a']['revision'], a_c5['revision']),
    }

    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(expected_picked_roll['commit_infos'],
                     picked_roll['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     picked_roll['spec'])
    self.assertEqual(
        0, picked_roll['recipes_simulation_test']['rc'])

  def test_find_minimal_candidate(self):
    """Tests that the roller can automatically find a viable minimal
    roll candidate, in a scenario where previous roll algorithm
    was getting stuck.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
        'c': ['b', 'a'],
    })
    b_package_spec = self.get_package_spec(repos['b'])
    c_package_spec = self.get_package_spec(repos['c'])

    # Set up a recipe in repo C depending on a module in repo B.
    b_c1 = self.update_recipe_module(repos['b'], 'b_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['c'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    c_c1 = self.update_recipe(
        repos['c'], 'c_recipe', ['b/b_module'], [('b_module', 'foo')])

    # Create a new commit in the A repo and roll it into B.
    a_c1 = self.commit_in_repo(repos['a'], message='c1')
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(
        str(b_package_spec.dump()).replace(
            repos['a']['revision'], a_c1['revision']),
        roll_result['picked_roll_details']['spec'])

    # Commit the roll.
    b_c2 = self.commit_in_repo(repos['b'], message='roll')

    # Change API of the recipe module in an incompatible way.
    b_c3 = self.update_recipe_module(repos['b'], 'b_module', {'baz': ['baz']})

    roll_result = self.run_roll(repos['c'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author': a_c1['author_email'],
                    'message': a_c1['message'],
                    'repo_id': 'a',
                    'revision': a_c1['revision'],
                },
            ],
            'b': [
                {
                    'author': b_c2['author_email'],
                    'message': b_c2['message'],
                    'repo_id': 'b',
                    'revision': b_c2['revision'],
                },
            ],
        },
        'spec': str(c_package_spec.dump()).replace(
            repos['a']['revision'], a_c1['revision']).replace(
                repos['b']['revision'], b_c2['revision']),
    }

    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(expected_picked_roll['commit_infos'],
                     picked_roll['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     picked_roll['spec'])
    self.assertEqual(
        0, picked_roll['recipes_simulation_test']['rc'])

  def test_no_backwards_roll(self):
    """Tests that we never roll backwards.
    """
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
        'c': ['b', 'a'],
    })
    root_repo_spec = self.get_root_repo_spec(repos['c'])
    b_repo_spec = self.get_git_repo_spec(repos['b'])
    c_package_spec = self.get_package_spec(repos['c'])

    # Create a new commit in A repo and roll it to B.
    a_c1 = self.commit_in_repo(repos['a'], message='c1')
    b_c1_rev = self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(repos['b'], 'a', a_c1['revision']))

    # Roll above commits to C.
    roll_result = self.run_roll(repos['c'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(
        str(c_package_spec.dump()).replace(
            repos['a']['revision'], a_c1['revision']).replace(
                repos['b']['revision'], b_c1_rev),
        roll_result['picked_roll_details']['spec'])

    # Create a new commit in B that would result in backwards roll.
    b_c2_rev = self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(
            repos['b'], 'a', repos['a']['revision']))

    roll_result = self.run_roll(repos['c'])
    self.assertFalse(roll_result['success'])
    self.assertEqual([], roll_result['roll_details'])

    expected_rejected_candidate = {
        'commit_infos': {
            'b': [
                b_repo_spec._get_commit_info(b_c2_rev, self._context).dump(),
            ],
        },
        'spec': str(c_package_spec.dump()).replace(
            repos['a']['revision'], a_c1['revision']).replace(
                repos['b']['revision'], b_c2_rev),
    }
    self.assertEqual(
        [expected_rejected_candidate],
        roll_result['rejected_candidates_details'])


if __name__ == '__main__':
  sys.exit(unittest.main())
