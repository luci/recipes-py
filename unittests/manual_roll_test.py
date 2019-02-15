#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import sys

from google.protobuf import json_format as jsonpb

import test_env

class ManualRollSmokeTest(test_env.RecipeEngineUnitTest):
  def run_roll(self, deps, should_fail=False):
    """Runs the autoroll command and returns JSON.
    Does not commit the resulting roll.
    """
    output, retcode = deps.main_repo.recipes_py('-v', '-v', 'manual_roll')
    expected_retcode = 1 if should_fail else 0
    self.assertEqual(
        retcode, expected_retcode,
        'unexpected retcode (%d vs %d)!\noutput:\n%s' % (
          retcode, expected_retcode, output))
    return output

  def test_empty(self):
    """No rolls are available."""
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    deps.main_repo.add_dep('upstream')
    deps.main_repo.commit('add dep on upstream')

    self.assertIn(
        'No roll found',
        self.run_roll(deps, should_fail=True))

  def test_single(self):
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    deps.main_repo.add_dep('upstream')
    deps.main_repo.commit('add dep on upstream')

    # Make an "interesting" change, otherwise the autoroller will ignore this
    # commit.
    with upstream.write_file('some_file') as fil:
      fil.write('hi')
    up_commit = upstream.commit('new commit')

    self.run_roll(deps)
    self.assertEqual(
        deps.main_repo.recipes_cfg_pb2.deps['upstream'].revision,
        up_commit.revision)

  def test_multi(self):
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')
    deps.main_repo.add_dep('upstream')
    deps.main_repo.commit('add dep on upstream')

    # Make an "interesting" change, otherwise the autoroller will ignore this
    # commit.
    with upstream.write_file('some_file') as fil:
      fil.write('hi')
    up_commit1 = upstream.commit('new commit')

    # Make an "interesting" change, otherwise the autoroller will ignore this
    # commit.
    with upstream.write_file('some_file') as fil:
      fil.write('sup')
    up_commit2 = upstream.commit('another new commit')

    self.run_roll(deps)
    self.assertEqual(
        deps.main_repo.recipes_cfg_pb2.deps['upstream'].revision,
        up_commit1.revision)

    self.run_roll(deps)
    self.assertEqual(
        deps.main_repo.recipes_cfg_pb2.deps['upstream'].revision,
        up_commit2.revision)


if __name__ == '__main__':
  test_env.main()
