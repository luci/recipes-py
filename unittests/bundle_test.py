#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import subprocess

import test_env


class TestBundle(test_env.RecipeEngineUnitTest):
  def test_simple(self):
    deps = self.FakeRecipeDeps()
    with deps.main_repo.write_recipe('foo') as recipe:
      recipe.DEPS = ['recipe_engine/python']
      recipe.RunSteps.write('''
        api.python.succeeding_step('hey there', "This is some narwhals.")
      ''')

    deps.main_repo.commit('save recipe')

    dest = self.tempdir()
    output, retcode = deps.main_repo.recipes_py('bundle', '--destination', dest)
    self.assertEqual(retcode, 0, 'bundling failed!\noutput:\n'+output)

    bat = '.bat' if sys.platform.startswith('win') else ''
    proc = subprocess.Popen(
        [os.path.join(dest, 'recipes'+bat), 'run', 'foo'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output, _ = proc.communicate()
    self.assertEqual(proc.returncode, 0, 'running failed!\noutput:\n'+output)
    self.assertIn('narwhals', output)


if __name__ == '__main__':
  test_env.main()
