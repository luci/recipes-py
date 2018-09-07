#!/usr/bin/env vpython
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Small smoke test that makes sure analyze works.

There are more extensive unit tests in //recipe_engine/unittests/analyze_test.py
This is just here to test the command end to end."""

import json
import os
import subprocess
import sys
import unittest

from repo_test_util import ROOT_DIR, temporary_file


class AnalyzeTest(unittest.TestCase):
  def testInvalidRecipe(self):
    with temporary_file() as input_path:
      with open(input_path, 'w') as f:
        json.dump({
            'files': ['recipe_modules/step/api.py'],
            'recipes': ['engine_tests/unicooooooode'],
        }, f)

      with temporary_file() as output_path:
        script_path = os.path.join(ROOT_DIR, 'recipes.py')
        exit_code = subprocess.call([
            sys.executable, script_path,
            '--package', os.path.join(
                ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
            'analyze', input_path, output_path])
        with open(output_path) as f:
          self.assertEqual(json.load(f), {
            'error': 'Some input recipes were invalid',
            'invalidRecipes': ['engine_tests/unicooooooode'],
          })
        self.assertEqual(1, exit_code)

  def testNotChanged(self):
    with temporary_file() as input_path:
      with open(input_path, 'w') as f:
        json.dump({
            'files': ['recipe_modules/buildbucket/api.py'],
            'recipes': ['engine_tests/unicode'],
        }, f)

      with temporary_file() as output_path:
        script_path = os.path.join(ROOT_DIR, 'recipes.py')
        exit_code = subprocess.call([
            sys.executable, script_path,
            '--package', os.path.join(
                ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
            'analyze', input_path, output_path])
        with open(output_path) as f:
          self.assertEqual(json.load(f), {})
        self.assertEqual(0, exit_code)

  def testGitAttrs(self):
    with temporary_file() as input_path:
      with open(input_path, 'w') as f:
        json.dump({
            'files': ['recipes.py'],
            'recipes': [
                'engine_tests/unicode',
                'engine_tests/whitelist_steps',
            ],
        }, f)

      with temporary_file() as output_path:
        script_path = os.path.join(ROOT_DIR, 'recipes.py')
        exit_code = subprocess.call([
            sys.executable, script_path,
            '--package', os.path.join(
                ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
            'analyze', input_path, output_path])
        with open(output_path) as f:
          self.assertEqual(json.load(f), {
            # List should be safe to not wrap with a call to sorted, since
            # proto repeated fields are ordered, so everything should be
            # analyzed in the same order every time.
            'recipes': [
              'engine_tests/whitelist_steps',
              'engine_tests/unicode',
            ],
          })
        self.assertEqual(0, exit_code)

  def testRecipeChanged(self):
    with temporary_file() as input_path:
      with open(input_path, 'w') as f:
        json.dump({
            'files': ['recipes/engine_tests/unicode.py'],
            'recipes': ['engine_tests/unicode'],
        }, f)

      with temporary_file() as output_path:
        script_path = os.path.join(ROOT_DIR, 'recipes.py')
        exit_code = subprocess.call([
            sys.executable, script_path,
            '--package', os.path.join(
                ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
            'analyze', input_path, output_path])
        with open(output_path) as f:
          self.assertEqual(json.load(f), {
            'recipes': ['engine_tests/unicode'],
          })
        self.assertEqual(0, exit_code)

  def testRecipeChangedAbsPath(self):
    with temporary_file() as input_path:
      with open(input_path, 'w') as f:
        json.dump({
            'files': [os.path.join(
                ROOT_DIR, 'recipes', 'engine_tests', 'unicode.py')],
            'recipes': ['engine_tests/unicode'],
        }, f)

      with temporary_file() as output_path:
        script_path = os.path.join(ROOT_DIR, 'recipes.py')
        exit_code = subprocess.call([
            sys.executable, script_path,
            '--package', os.path.join(
                ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
            'analyze', input_path, output_path])
        with open(output_path) as f:
          self.assertEqual(json.load(f), {
            'recipes': ['engine_tests/unicode'],
          })
        self.assertEqual(0, exit_code)

  def testModuleChanged(self):
    with temporary_file() as input_path:
      with open(input_path, 'w') as f:
        json.dump({
            'files': ['recipe_modules/step/api.py'],
            'recipes': ['engine_tests/unicode'],
        }, f)

      with temporary_file() as output_path:
        script_path = os.path.join(ROOT_DIR, 'recipes.py')
        exit_code = subprocess.call([
            sys.executable, script_path,
            '--package', os.path.join(
                ROOT_DIR, 'infra', 'config', 'recipes.cfg'),
            'analyze', input_path, output_path])
        with open(output_path) as f:
          self.assertEqual(json.load(f), {
            'recipes': ['engine_tests/unicode'],
          })
        self.assertEqual(0, exit_code)


if __name__ == '__main__':
  unittest.TestCase.maxDiff = None
  unittest.main()
