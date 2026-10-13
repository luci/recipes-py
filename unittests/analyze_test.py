#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests for the 'analyze' command."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
import subprocess
import sys
from typing import Any
from unittest import mock

import test_env

from PB.recipe_engine import analyze as analyze_pb
from recipe_engine.internal import recipe_deps as recipe_deps_mod
from recipe_engine.internal.commands.analyze import cmd as analyze


class AnalyzeTest(test_env.RecipeEngineUnitTest):
  def setUp(self) -> None:
    super().setUp()
    self.git_attr_patcher = mock.patch(
        'recipe_engine.internal.commands.analyze.cmd.get_git_attribute_files',
        side_effect=self.git_attr)
    self.git_attr_patcher.start()
    self.git_attr_files: Sequence[str] | None = []

  def tearDown(self) -> None:
    self.git_attr_patcher.stop()
    self.git_attr_files = None
    super().tearDown()

  def git_attr(self, repo_root: str) -> list[str]:
    assert self.git_attr_files is not None
    return [os.path.join(repo_root, path) for path in self.git_attr_files]

  def _run(
      self,
      recipe_deps: recipe_deps_mod.RecipeDeps,
      git_attr_files: Sequence[str],
      in_data: analyze_pb.Input,
  ) -> analyze_pb.Output:
    self.git_attr_files = git_attr_files
    result = analyze.analyze(recipe_deps, in_data)
    result.recipes.sort()
    result.invalid_recipes.sort()

    return result

  def testInvalidRecipe(self) -> None:
    result = self._run(
      self.MockRecipeDeps(),
      git_attr_files=[], in_data=analyze_pb.Input(
        files=['foo.py'],
        recipes=['run_test.py'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      error='Some input recipes were invalid',
      invalid_recipes=['run_test.py'],
    ))

  def testUnusedFiles(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['some_random_file'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb.Output())

  def testGitAttrs(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {
          'run_test': ['foo_module'],
          'other_thing': ['foo_module'],
          'last_recipe': ['foo_module'],
        }
      ), git_attr_files=['foo.py'], in_data=analyze_pb.Input(
          files=['foo.py'],
          recipes=['run_test', 'other_thing', 'last_recipe'],
      ))
    self.assertEqual(result, analyze_pb.Output(
        recipes=sorted(['run_test', 'other_thing', 'last_recipe']),
    ))

  def testSimple(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=['run_test'],
    ))

  def testAbsPath(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['/MAIN_ROOT/recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=['run_test'],
    ))

  def testRecipeFile(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipes/run_test.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=['run_test'],
    ))

  def testDependency(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {
          'foo_module': ['bar_module'],
          'bar_module': [],
        },
        {'run_test': ['foo_module']}
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipe_modules/bar_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=['run_test'],
    ))

  def testTwoRecipes(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {
          'run_test': ['foo_module'],
          'run_other_test': ['foo_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test', 'run_other_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=sorted(['run_test', 'run_other_test']),
    ))

  def testTwoRecipesOnlyOne(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {'foo_module': []},
        {
          'run_test': ['foo_module'],
          'run_other_test': [],
        }
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test', 'run_other_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=['run_test'],
    ))

  def testOneRecipeTwoModules(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {
          'foo_module': [],
          'bar_module': [],
        },
        {
          'run_test': ['foo_module', 'bar_module'],
        }
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipe_modules/foo_module/api.py'],
          recipes=['run_test'],
      ))
    self.assertEqual(result, analyze_pb.Output(
      recipes=['run_test'],
    ))

  def testSimilarModuleChanged(self) -> None:
    result = self._run(self.MockRecipeDeps(
        {
          'foo': [],
          'foo_bar': [],
        },
        {
          'recipe': ['foo'],
        }
      ), git_attr_files=[], in_data=analyze_pb.Input(
          files=['recipe_modules/foo_bar/api.py'],
          recipes=['recipe'],
      ))
    self.assertEqual(result, analyze_pb.Output())


class AnalyzeSmokeTest(test_env.RecipeEngineUnitTest):
  """Small smoke test that makes sure analyze works.
  """

  def _run(self, indata: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    infile = self.tempfile()
    with open(infile, 'w') as f:
      json.dump(indata, f)

    outfile = self.tempfile()
    exit_code = subprocess.call([
      sys.executable, os.path.join(test_env.ROOT_DIR, 'recipes.py'),
      'analyze', infile, outfile])
    with open(outfile) as f:
      return exit_code, json.load(f)

  def testInvalidRecipe(self) -> None:
    exit_code, outdata = self._run({
      'files': ['recipe_modules/step/api.py'],
      'recipes': ['engine_tests/unicooooooode'],
    })
    self.assertDictEqual(outdata, {
      'error': 'Some input recipes were invalid',
      'invalidRecipes': ['engine_tests/unicooooooode'],
      'recipes': [],
    })
    self.assertEqual(exit_code, 1)

  def testNotChanged(self) -> None:
    # The test here assumes that unicode recipe has no direct or indirect
    # dependencies on tricium recipe_module. If you invalidate this assumption,
    # you should change this test.
    exit_code, outdata = self._run({
      'files': ['recipe_modules/tricium/api.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': [],
    })
    self.assertEqual(exit_code, 0)

  def testGitAttrs(self) -> None:
    exit_code, outdata = self._run({
        'files': ['vpython.toml'],  # vpython is included via .gitattributes
        'recipes': [
            'engine_tests/unicode',
            'engine_tests/allowlist_steps',
        ],
    })
    self.assertDictEqual(
        outdata, {
            'error':
                '',
            'invalidRecipes': [],
            'recipes': [
                'engine_tests/unicode',
                'engine_tests/allowlist_steps',
            ],
        })
    self.assertEqual(exit_code, 0)

  def testRecipeChanged(self) -> None:
    exit_code, outdata = self._run({
      'files': ['recipes/engine_tests/unicode.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)

  def testRecipeResourceChanged(self) -> None:
    exit_code, outdata = self._run({
      'files': ['recipes/engine_tests/unicode.resources/helper.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)

  def testRecipeChangedAbsPath(self) -> None:
    exit_code, outdata = self._run({
            'files': [os.path.join(
                test_env.ROOT_DIR, 'recipes', 'engine_tests', 'unicode.py')],
            'recipes': ['engine_tests/unicode'],
        })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)

  def testModuleChanged(self) -> None:
    exit_code, outdata = self._run({
      'files': ['recipe_modules/step/api.py'],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertDictEqual(outdata, {
      'error': '',
      'invalidRecipes': [],
      'recipes': ['engine_tests/unicode'],
    })
    self.assertEqual(exit_code, 0)


if __name__ == '__main__':
  test_env.main()
