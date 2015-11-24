#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import subprocess
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__))))
THIRD_PARTY = os.path.join(BASE_DIR, 'recipe_engine', 'third_party')
sys.path.insert(0, os.path.join(THIRD_PARTY, 'mock-1.0.1'))
sys.path.insert(0, BASE_DIR)

import recipe_engine.run
from recipe_engine import recipe_test_api
import mock

class RunTest(unittest.TestCase):
  def test_run(self):
    script_path = os.path.join(BASE_DIR, 'recipes.py')
    exit_code = subprocess.call([
        'python', script_path,
        '--package', os.path.join(BASE_DIR, 'infra', 'config', 'recipes.cfg'),
        'run', 'step:example'])
    self.assertEqual(0, exit_code)

  def test_shell_quote(self):
    # For regular-looking commands we shouldn't need any specialness.
    self.assertEqual(
        recipe_engine.run._shell_quote('/usr/bin/python-wrapper.bin'),
        '/usr/bin/python-wrapper.bin')

    STRINGS = [
        'Simple.Command123/run',
        'Command with spaces',
        'Command with "quotes"',
        "I have 'single quotes'",
        'Some \\Esc\ape Seque\nces/',
        u'Unicode makes me \u2609\u203f\u2299',
    ]

    for s in STRINGS:
      quoted = recipe_engine.run._shell_quote(s)

      # We shouldn't ever get an actual newline in a command, that's awful
      # for copypasta.
      self.assertNotRegexpMatches(quoted, '\n')

      # We should be able to paste any argument into bash & zsh and get
      # exactly what subprocess did.
      bash_output = subprocess.check_output([
          'bash', '-c', '/bin/echo %s' % quoted])
      self.assertEqual(bash_output.decode('utf-8'), s + '\n')

      zsh_output = subprocess.check_output([
          'zsh', '-c', '/bin/echo %s' % quoted])
      self.assertEqual(zsh_output.decode('utf-8'), s + '\n')

  def test_run_unconsumed(self):
    stream = mock.Mock()
    properties = {}

    test_data = mock.Mock()
    test_data.enabled = True
    test_data.consumed = False

    api = mock.Mock()
    api._engine = mock.Mock()
    api._engine.properties = properties

    engine = recipe_engine.run.RecipeEngine(stream, properties, test_data, None)

    class FakeScript(object):
      def run(self, _, __):
        return None

    with mock.patch('recipe_engine.run.RecipeEngine._emit_results'):
      with self.assertRaises(AssertionError):
        engine.run(FakeScript(), api)


if __name__ == '__main__':
  unittest.TestCase.maxDiff = None
  unittest.main()
