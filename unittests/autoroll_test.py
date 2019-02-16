#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import sys

from google.protobuf import json_format as jsonpb

import test_env


def add_repo_with_basic_upstream_dependency(deps):
  """Does:

  Create `upstream` repo with `up_mod` module, containing a single method
  `cool_step`.

  Make the main repo depend on this module, and use the module for a recipe
  `my_recipe`.

  Run simulation training for the main repo, and commit the result.
  """
  upstream = deps.add_repo('upstream')

  # Set up a recipe in main_repo depending on a module in upstream
  with upstream.write_module('up_mod') as mod:
    mod.api.write('''
    def cool_method(self):
      self.m.step('upstream step', ['echo', 'whats up'])
    ''')
  up_commit = upstream.commit('add "up_mod"')

  # Now use the upstream module in main_repo
  with deps.main_repo.edit_recipes_cfg_pb2() as pkg_pb:
    pkg_pb.deps['upstream'].revision = up_commit.revision

  with deps.main_repo.write_file('recipes/my_recipe.py') as buf:
    buf.write('''
    DEPS=['upstream/up_mod']
    def RunSteps(api):
      api.up_mod.cool_method()
    def GenTests(api):
      yield api.test('basic')
    ''')
  deps.main_repo.recipes_py('test', 'train')
  deps.main_repo.commit('depend on upstream/up_mod')


class AutorollSmokeTest(test_env.RecipeEngineUnitTest):
  def run_roll(self, deps, *args):
    """Runs the autoroll command and returns JSON.
    Does not commit the resulting roll.
    """
    outfile = self.tempfile()
    output, retcode = deps.main_repo.recipes_py(
      '-v', '-v', 'autoroll', '--verbose-json', '--output-json',
      outfile, *args
    )
    if retcode != 0:
      print >> sys.stdout, output
      raise Exception('Roll failed')
    with open(outfile) as fil:
      return json.load(fil)

  def test_empty(self):
    """Tests the scenario where there are no roll candidates."""
    deps = self.FakeRecipeDeps()

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertEqual([], roll_result['roll_details'])
    self.assertEqual([], roll_result['rejected_candidate_specs'])

  def test_trivial(self):
    """Tests the simplest trivial (i.e. no expectation changes) roll scenario.
    """
    # prep
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')

    with upstream.write_file('some_file') as buf:
      buf.write('hi!')
    upstream_commit = upstream.commit('c1')

    # test
    spec = deps.main_repo.recipes_cfg_pb2
    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    spec.deps['upstream'].revision = upstream_commit.revision

    expected_picked_roll = {
      'commit_infos': {
        'upstream': [
          upstream_commit.as_roll_info(),
        ],
      },
      'spec': jsonpb.MessageToDict(spec, preserving_proto_field_name=True),
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
    deps = self.FakeRecipeDeps()
    add_repo_with_basic_upstream_dependency(deps)
    upstream = deps.repos['upstream']

    spec = deps.main_repo.recipes_cfg_pb2

    # Change implementation of up_mod in a way that's compatible, but changes
    # expectations.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats down'])
      ''')
    up_commit = upstream.commit('change "up_mod"')

    # Roll again, and we can see the non-trivial roll now.
    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    spec.deps['upstream'].revision = up_commit.revision

    expected_picked_roll = {
      'commit_infos': {
        'upstream': [
          up_commit.as_roll_info()
        ],
      },
      'spec': jsonpb.MessageToDict(spec, preserving_proto_field_name=True),
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
    deps = self.FakeRecipeDeps()
    add_repo_with_basic_upstream_dependency(deps)
    upstream = deps.repos['upstream']

    # Change API of the recipe module in a totally incompatible way.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def uncool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    upstream.commit('add incompatibility')

    # watch our roll fail
    roll_result = self.run_roll(deps)
    self.assertFalse(roll_result['success'])

  def test_jump_over_failure(self):
    """Tests whether the roller considers pulling more commits to make
    the roll succeed, when earlier ones have incompatible API changes
    fixed later.
    """
    deps = self.FakeRecipeDeps()
    add_repo_with_basic_upstream_dependency(deps)
    upstream = deps.repos['upstream']

    spec = deps.main_repo.recipes_cfg_pb2

    # Change API of the recipe module in an incompatible way.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def uncool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    middle_commit = upstream.commit('add incompatibility')

    # Restore compatibility, but change expectations.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats down'])
      ''')
    final_commit = upstream.commit('restore similar method')

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    spec.deps['upstream'].revision = final_commit.revision

    expected_picked_roll = {
      'commit_infos': {
        'upstream': [
          middle_commit.as_roll_info(),
          final_commit.as_roll_info(),
        ],
      },
      'spec': jsonpb.MessageToDict(spec, preserving_proto_field_name=True),
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
    deps = self.FakeRecipeDeps()
    add_repo_with_basic_upstream_dependency(deps)
    upstream = deps.repos['upstream']

    spec = deps.main_repo.recipes_cfg_pb2

    # Change API of the recipe module in an incompatible way.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def uncool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    middle_commit = upstream.commit('add incompatibility')

    # Restore compatibility, but change expectations.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats down'])
      ''')
    final_commit = upstream.commit('restore similar method')

    # Create another change that would result in a nontrivial roll,
    # which should not be picked - nontrivial rolls should be minimal.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats superdown'])
      ''')
    upstream.commit('second nontrivial change')

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertFalse(roll_result['trivial'])

    spec.deps['upstream'].revision = final_commit.revision

    expected_picked_roll = {
      'commit_infos': {
        'upstream': [
          middle_commit.as_roll_info(),
          final_commit.as_roll_info(),
        ],
      },
      'spec': jsonpb.MessageToDict(spec, preserving_proto_field_name=True),
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
    deps = self.FakeRecipeDeps()
    add_repo_with_basic_upstream_dependency(deps)
    upstream = deps.repos['upstream']

    spec = deps.main_repo.recipes_cfg_pb2

    # Change API of the recipe module in an incompatible way.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def uncool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    first_commit = upstream.commit('add incompatibility')

    # Restore compatibility, but change expectations.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats down'])
      ''')
    second_commit = upstream.commit('restore similar method')

    # Create another change that would result in a nontrivial roll,
    # which should not be picked - nontrivial rolls should be minimal.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats superdown'])
      ''')
    third_commit = upstream.commit('second nontrivial change')

    # Introduce another commit which makes the roll trivial again.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    final_commit = upstream.commit('restore original behavior')

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    spec.deps['upstream'].revision = final_commit.revision

    expected_picked_roll = {
      'commit_infos': {
        'upstream': [
          first_commit.as_roll_info(),
          second_commit.as_roll_info(),
          third_commit.as_roll_info(),
          final_commit.as_roll_info(),
        ],
      },
      'spec': jsonpb.MessageToDict(spec, preserving_proto_field_name=True),
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
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    super_upstream = deps.add_repo('super_upstream')

    spec = deps.main_repo.recipes_cfg_pb2

    # Now make upstream depend on super_upstream, then roll that into the main
    # repo.
    upstream.add_dep('super_upstream')
    super_commit = upstream.commit('add dep on super_upstream')

    with deps.main_repo.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['upstream'].revision = super_commit.revision
    deps.main_repo.commit('roll upstream')

    # Set up a recipe in the main repo depending on a module in upstream.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def cool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    up_commit = upstream.commit('add up_mod')

    with deps.main_repo.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['upstream'].revision = up_commit.revision
    with deps.main_repo.write_file('recipes/my_recipe.py') as buf:
      buf.write('''
      DEPS=['upstream/up_mod']
      def RunSteps(api):
        api.up_mod.cool_method()
      def GenTests(api):
        yield api.test('basic')
      ''')
    deps.main_repo.recipes_py('test', 'train')
    deps.main_repo.commit('depend on upstream/up_mod')

    # Create a new commit in super_uptsream repo and roll it into upstream.
    super_commit = super_upstream.commit('trivial commit')
    with upstream.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['super_upstream'].revision = super_commit.revision
    super_roll = upstream.commit('roll super_upstream')

    # Change API of the upstream module in an incompatible way.
    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def uncool_method(self):
        self.m.step('upstream step', ['echo', 'whats up'])
      ''')
    up_commit = upstream.commit('incompatible up_mod')

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertTrue(roll_result['trivial'])

    spec.deps['super_upstream'].revision = super_commit.revision
    spec.deps['upstream'].revision = super_roll.revision

    expected_picked_roll = {
        'commit_infos': {
            'upstream': [super_roll.as_roll_info()],
            'super_upstream': [super_commit.as_roll_info()],
        },
      'spec': jsonpb.MessageToDict(spec, preserving_proto_field_name=True),
    }

    picked_roll = roll_result['picked_roll_details']
    self.assertEqual(expected_picked_roll['commit_infos'],
                     picked_roll['commit_infos'])
    self.assertEqual(expected_picked_roll['spec'],
                     picked_roll['spec'])
    self.assertEqual(
        0, picked_roll['recipes_simulation_test']['rc'])

  def test_no_backwards_roll(self):
    """Tests that we never roll backwards."""
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    super_upstream = deps.add_repo('super_upstream')

    original_super_commit = super_upstream.backend.commit_metadata('HEAD')

    upstream.add_dep('super_upstream')
    upstream.commit('add dep on super_upstream')

    # Create a new commit in super_upstream repo and roll it to upstream.
    super_commit = super_upstream.commit('trivial commit')
    with upstream.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['super_upstream'].revision = super_commit.revision
    up_commit = upstream.commit('roll')

    # Roll above commits to main_repo.
    with deps.main_repo.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['upstream'].revision = up_commit.revision
      pkg_pb.deps['super_upstream'].revision = super_commit.revision
    deps.main_repo.commit('roll upstream+super_upstream')

    spec = deps.main_repo.recipes_cfg_pb2

    # Create a new commit in upstream that would result in backwards roll.
    with upstream.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['super_upstream'].revision = original_super_commit.revision
    up_commit = upstream.commit('backwards commit')

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertEqual([], roll_result['roll_details'])

    spec.deps['upstream'].revision = up_commit.revision

    self.assertEqual(
      roll_result['rejected_candidate_specs'],
      [jsonpb.MessageToDict(spec, preserving_proto_field_name=True)],
    )


  def test_inconsistent_errors(self):
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    upstream_deeper = deps.add_repo('upstream_deeper')
    upstream_deepest = deps.add_repo('upstream_deepest')

    # Add:
    #   upstream_deeper -> upstream_deepest
    #   upstream -> upstream_deeper
    #   upstream -> upstream_deepest
    upstream_deeper.add_dep('upstream_deepest')
    upstream_deeper.commit('add dep on upstream_deepest')

    upstream.add_dep('upstream_deeper', 'upstream_deepest')
    upstream.commit('add dep on upstream_deepest + upstream_deeper')

    # Roll all of that into main.
    self.run_roll(deps)

    # Create a new commit in deepest repo and roll it to deeper.
    deepest_commit = upstream_deepest.commit('deep commit')
    with upstream_deeper.edit_recipes_cfg_pb2() as pkg_pb:
      pkg_pb.deps['upstream_deepest'].revision = deepest_commit.revision
    upstream_deeper.commit('roll deepest')

    # We shouldn't be able to roll upstream_deeper/upstream_deepest until
    # upstream includes them. i.e. there should be no roll, because there are no
    # valid roll candidates.

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertEqual([], roll_result['roll_details'])
    self.assertGreater(len(roll_result['rejected_candidate_specs']), 0)

  def test_roll_adds_dependency(self):
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    other = deps.add_repo('other')

    with deps.main_repo.edit_recipes_cfg_pb2() as spec:
      del spec.deps['other']
    deps.main_repo.commit('remove other dep')

    spec = deps.main_repo.recipes_cfg_pb2
    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    self.assertEqual(spec, deps.main_repo.recipes_cfg_pb2)  # noop

    # Now we add a commit to 'upstream' which pulls in 'other'.
    upstream.add_dep('other')
    upstream.commit('add other dep')
    with upstream.write_file('trivial') as fil:
      fil.write('trivial file')
    up_commit = upstream.commit('add trivial file')

    roll_result = self.run_roll(deps)
    self.assertTrue(roll_result['success'])
    spec.deps['upstream'].revision = up_commit.revision
    spec.deps['other'].CopyFrom(upstream.recipes_cfg_pb2.deps['other'])
    self.assertEqual(spec, deps.main_repo.recipes_cfg_pb2)


if __name__ == '__main__':
  test_env.main()
