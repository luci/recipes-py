#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import json
import logging
import os
import subprocess
import sys
import unittest

import repo_test_util

from recipe_engine import package_io


class TestAutoroll(repo_test_util.RepoTest):
  def run_roll(self, repo, *args):
    """Runs the autoroll command and returns JSON.
    Does not commit the resulting roll.
    """
    try:
      with repo_test_util.in_directory(repo['root']), \
          repo_test_util.temporary_file() as tempfile_path:
        subprocess.check_output([
          sys.executable, self._recipe_tool,
          '-v', '-v', '--package', os.path.join(
            repo['root'], 'infra', 'config', 'recipes.cfg'),
          '--use-bootstrap',
          'autoroll',
          '--output-json', tempfile_path,
          '--verbose-json'
        ] + list(args) , stderr=subprocess.STDOUT)
        with open(tempfile_path) as f:
          return json.load(f)
    except subprocess.CalledProcessError as e:
      print >> sys.stdout, e.output
      raise

  def test_empty(self):
    """Tests the scenario where there are no roll candidates.
    """
    repos = self.repo_setup({
        'a': [],
    })

    roll_result = self.run_roll(repos['a'])
    self.assertTrue(roll_result['success'])
    self.assertEquals([], roll_result['roll_details'])
    self.assertEquals([], roll_result['rejected_candidate_specs'])

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

    spec = copy.deepcopy(b_package_spec.spec_pb)
    spec.deps['a'].revision = a_c1['revision']

    expected_picked_roll = {
      'commit_infos': {
        'a': [
          {
            'author_email': a_c1['author_email'],
            'message_lines': a_c1['message_lines'],
            'revision': a_c1['revision'],
          },
        ],
      },
      'spec': package_io.dump_obj(spec),
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
    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in a way that's compatible,
    # but changes expectations.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    spec = copy.deepcopy(b_package_spec.spec_pb)
    spec.deps['a'].revision = a_c2['revision']

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author_email': a_c2['author_email'],
                    'message_lines': a_c2['message_lines'],
                    'revision': a_c2['revision'],
                },
            ],
        },
        'spec': package_io.dump_obj(spec),
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
    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

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
    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

    # Restore compatibility, but change expectations.
    a_c3 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    spec = copy.deepcopy(b_package_spec.spec_pb)
    spec.deps['a'].revision = a_c3['revision']

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author_email': a_c2['author_email'],
                    'message_lines': a_c2['message_lines'],
                    'revision': a_c2['revision'],
                },
                {
                    'author_email': a_c3['author_email'],
                    'message_lines': a_c3['message_lines'],
                    'revision': a_c3['revision'],
                },
            ],
        },
        'spec': package_io.dump_obj(spec),
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
    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    self.update_recipe(
        repos['b'], 'b_recipe', ['a/a_module'], [('a_module', 'foo')])

    # Change API of the recipe module in an incompatible way.
    a_c2 = self.update_recipe_module(repos['a'], 'a_module', {'baz': ['baz']})

    # Restore compatibility, but change expectations.
    a_c3 = self.update_recipe_module(repos['a'], 'a_module', {'foo': ['baz']})

    # Create another change that would result in a nontrivial roll,
    # which should not be picked - nontrivial rolls should be minimal.
    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bam']})

    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    spec = copy.deepcopy(b_package_spec.spec_pb)
    spec.deps['a'].revision = a_c3['revision']

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author_email': a_c2['author_email'],
                    'message_lines': a_c2['message_lines'],
                    'revision': a_c2['revision'],
                },
                {
                    'author_email': a_c3['author_email'],
                    'message_lines': a_c3['message_lines'],
                    'revision': a_c3['revision'],
                },
            ],
        },
        'spec': package_io.dump_obj(spec),
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
    self.update_recipe_module(repos['a'], 'a_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    self.update_recipe(
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

    spec = copy.deepcopy(b_package_spec.spec_pb)
    spec.deps['a'].revision = a_c5['revision']

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author_email': a_c2['author_email'],
                    'message_lines': a_c2['message_lines'],
                    'revision': a_c2['revision'],
                },
                {
                    'author_email': a_c3['author_email'],
                    'message_lines': a_c3['message_lines'],
                    'revision': a_c3['revision'],
                },
                {
                    'author_email': a_c4['author_email'],
                    'message_lines': a_c4['message_lines'],
                    'revision': a_c4['revision'],
                },
                {
                    'author_email': a_c5['author_email'],
                    'message_lines': a_c5['message_lines'],
                    'revision': a_c5['revision'],
                },
            ],
        },
        'spec': package_io.dump_obj(spec),
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
    self.update_recipe_module(repos['b'], 'b_module', {'foo': ['bar']})
    roll_result = self.run_roll(repos['c'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    self.update_recipe(
        repos['c'], 'c_recipe', ['b/b_module'], [('b_module', 'foo')])

    # Create a new commit in the A repo and roll it into B.
    a_c1 = self.commit_in_repo(repos['a'], message='c1')
    roll_result = self.run_roll(repos['b'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])
    picked_roll = roll_result['picked_roll_details']

    spec = copy.deepcopy(b_package_spec.spec_pb)
    spec.deps['a'].revision = a_c1['revision']

    self.assertEqual(
        package_io.dump_obj(spec),
        roll_result['picked_roll_details']['spec'])

    # Commit the roll.
    b_c2 = self.commit_in_repo(repos['b'], message='roll')

    # Change API of the recipe module in an incompatible way.
    self.update_recipe_module(repos['b'], 'b_module', {'baz': ['baz']})

    roll_result = self.run_roll(repos['c'])
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    spec = copy.deepcopy(c_package_spec.spec_pb)
    spec.deps['a'].revision = a_c1['revision']
    spec.deps['b'].revision = b_c2['revision']

    expected_picked_roll = {
        'commit_infos': {
            'a': [
                {
                    'author_email': a_c1['author_email'],
                    'message_lines': a_c1['message_lines'],
                    'revision': a_c1['revision'],
                },
            ],
            'b': [
                {
                    'author_email': b_c2['author_email'],
                    'message_lines': b_c2['message_lines'],
                    'revision': b_c2['revision'],
                },
            ],
        },
        'spec': package_io.dump_obj(spec),
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
    self.get_root_repo_spec(repos['c'])
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

    spec = copy.deepcopy(c_package_spec.spec_pb)
    spec.deps['a'].revision = a_c1['revision']
    spec.deps['b'].revision = b_c1_rev

    self.assertEqual(
        package_io.dump_obj(spec),
        picked_roll['spec'])

    # Create a new commit in B that would result in backwards roll.
    b_new_rev = self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(
            repos['b'], 'a', repos['a']['revision']))

    roll_result = self.run_roll(repos['c'])
    self.assertTrue(roll_result['success'])
    self.assertEqual([], roll_result['roll_details'])

    spec.deps['b'].revision = b_new_rev

    self.assertEqual(
      roll_result['rejected_candidate_specs'],
      [package_io.dump_obj(spec)],
    )


  def test_inconsistent_errors(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
        'c': ['a', 'b'],
        'd': ['a', 'b', 'c'],
    })

    # Create a new commit in A repo and roll it to B.
    a_c1 = self.commit_in_repo(repos['a'], message='c1')
    self.update_recipes_cfg(
        'b', self.updated_package_spec_pb(repos['b'], 'a', a_c1['revision']))

    roll_result = self.run_roll(repos['d'])
    self.assertTrue(roll_result['success'])
    self.assertEqual([], roll_result['roll_details'])
    self.assertGreater(len(roll_result['rejected_candidate_specs']), 0)


if __name__ == '__main__':
  if '-v' in sys.argv:
    logging.basicConfig(
      level=logging.DEBUG,
      handler=repo_test_util.CapturableHandler())
  sys.exit(unittest.main())
