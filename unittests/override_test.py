#!/usr/bin/env vpython3
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import contextlib
import copy
import os
import shutil
import subprocess
import sys

import test_env

from recipe_engine.internal.simple_cfg import RECIPES_CFG_LOCATION_REL


@contextlib.contextmanager
def fake_git():
  fake_git_dir = os.path.join(test_env.ROOT_DIR, 'unittests', 'fakegit')
  cur_path = os.environ['PATH']
  try:
    os.environ['PATH'] = os.pathsep.join([fake_git_dir, cur_path])
    yield
  finally:
    os.environ['PATH'] = cur_path


class TestOverride(test_env.RecipeEngineUnitTest):
  def test_simple(self):
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')

    with upstream.write_module('up_mod') as mod:
      mod.api.write('''
      def foo(self):
        self.m.step('do the foo', ['echo', 'foo'])
      ''')
    up_commit = upstream.commit('add up_mod')

    with deps.main_repo.edit_recipes_cfg_pb2() as pb:
      pb.deps['upstream'].revision = up_commit.revision
    with deps.main_repo.write_recipe('my_recipe') as recipe:
      recipe.DEPS = ['upstream/up_mod']
      recipe.RunSteps.write('''
        api.up_mod.foo()
      ''')

    # Training the recipes should work.
    deps.main_repo.recipes_py('test', 'train')
    deps.main_repo.commit('add my_recipe')

    # Using upstream no-op override should also work.
    deps.main_repo.recipes_py('-O', 'upstream='+upstream.path,
                              'test', 'train')

    # Make another repo, then remove our dependency on it.
    other_upstream = deps.add_repo('other_upstream')
    with deps.main_repo.edit_recipes_cfg_pb2() as pb:
      del pb.deps['other_upstream']

    # Then using an override pointing to a repo without up_mod should fail.
    output, retcode = deps.main_repo.recipes_py(
      '-O', 'upstream='+other_upstream.path, 'test', 'train')
    self.assertEqual(retcode, 1)
    self.assertIn(
        ('"No module named \'up_mod\' in repo \'other_upstream\'."'),
        output)

  def test_bundle(self):
    deps = self.FakeRecipeDeps()
    upstream = deps.add_repo('upstream')

    with fake_git():
      # Training the recipes, overriding just 'upstream' should fail because
      # it will try to fetch the engine.
      output, retcode = deps.main_repo.recipes_py(
          # Provide --package to bypass all git calls in recipes.py
          '--package',
          os.path.join(deps.main_repo.path, RECIPES_CFG_LOCATION_REL),
          '-O', 'upstream='+upstream.path,
          'test', 'train'
      )
      self.assertEqual(retcode, 1)
      self.assertIn('Git "init" failed', output)

      output, retcode = deps.main_repo.recipes_py(
          '--package',
          os.path.join(deps.main_repo.path,
                       RECIPES_CFG_LOCATION_REL), '--proto-override',
          os.path.join(test_env.ROOT_DIR, '.recipe_deps',
                       '_pb%s' % sys.version[0]), '-O',
          'upstream=' + upstream.path, '-O',
          'recipe_engine=' + test_env.ROOT_DIR, 'test', 'train')
      self.assertEqual(retcode, 0, output)

if __name__ == '__main__':
  sys.exit(test_env.main())
