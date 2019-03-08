#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os
import re
import shutil
import subprocess
import sys
import time

import test_env

from recipe_engine.internal import step_runner


class RunTest(test_env.RecipeEngineUnitTest):
  def test_run(self):
    deps = self.FakeRecipeDeps()

    with deps.main_repo.write_module('mod') as mod:
      mod.api.write('''
      def do_thing(self):
        self.m.step('do the thing', ['echo', 'thing'])
      ''')
    with deps.main_repo.write_recipe('my_recipe') as recipe:
      recipe.DEPS = ['mod']
      recipe.RunSteps.write('''
        api.mod.do_thing()
      ''')
      recipe.GenTests.write('pass')

    _, retcode = deps.main_repo.recipes_py('-v', '-v', 'run', 'my_recipe')
    self.assertEqual(retcode, 0)


class RunSmokeTest(test_env.RecipeEngineUnitTest):
  def _run_cmd(self, recipe, properties=None, engine_args=()):
    script_path = os.path.join(test_env.ROOT_DIR, 'recipes.py')

    proplist = [
      '%s=%s' % (k, json.dumps(v)) for k, v in (properties or {}).iteritems()
    ]

    return (
      ['python', script_path] +
      list(engine_args) +
      ['run', recipe] +
      proplist
    )

  def _test_recipe(self, recipe, properties=None, env=None):
    proc = subprocess.Popen(
        self._run_cmd(recipe, properties),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env)
    stdout = proc.communicate()
    self.assertEqual(0, proc.returncode, '%d != %d when testing %s:\n%s' % (
        0, proc.returncode, recipe, stdout))

  def test_examples(self):
    env = os.environ.copy()

    # Set the "RECIPE_ENGINE_CONTEXT_TEST" environment variable to a known
    # value, "default". This is used by the "context:tests/env" recipe module
    # as a basis for runtime tests.
    env['RECIPE_ENGINE_CONTEXT_TEST'] = 'default'

    tests = [
      ['context:examples/full'],
      ['context:tests/env'],
      ['step:examples/full'],
      ['path:examples/full'],
      ['raw_io:examples/full'],
      ['python:examples/full'],
      ['json:examples/full'],
      ['file:examples/copy'],
      ['file:examples/copytree'],
      ['file:examples/glob'],

      ['engine_tests/functools_partial'],
    ]
    for test in tests:
      self._test_recipe(*test, env=env)

  def test_bad_subprocess(self):
    now = time.time()
    self._test_recipe('engine_tests/bad_subprocess')
    after = time.time()

    # Test has a daemon that holds on to stdout for 30s, but the daemon's parent
    # process (e.g. the one that recipe engine actually runs) quits immediately.
    # If this takes longer than 5 seconds to run, we consider it failed.
    self.assertLess(after - now, 5)


  def test_nonexistent_command(self):
    subp = subprocess.Popen(
        self._run_cmd('engine_tests/nonexistent_command'),
        stdout=subprocess.PIPE)
    stdout, _ = subp.communicate()

    self.assertRegexpMatches(stdout, '(?m)^@@@STEP_EXCEPTION@@@$')
    self.assertRegexpMatches(stdout, 'OSError')
    self.assertEqual(1, subp.returncode, stdout)

  def test_trigger(self):
    subp = subprocess.Popen(
        self._run_cmd('step:tests/trigger'),
        stdout=subprocess.PIPE)
    stdout, _ = subp.communicate()
    self.assertEqual(0, subp.returncode)
    m = re.compile(r'^@@@STEP_TRIGGER@(.*)@@@$', re.MULTILINE).search(stdout)
    self.assertTrue(m)
    blob = m.group(1)
    json.loads(blob) # Raises an exception if the blob is not valid json.

  def test_trigger_no_such_command(self):
    """Tests that trigger still happens even if running the command fails."""
    subp = subprocess.Popen(
        self._run_cmd(
            'step:tests/trigger', properties={'command': ['na-huh']}),
        stdout=subprocess.PIPE)
    stdout, _ = subp.communicate()

    self.assertRegexpMatches(stdout, r'(?m)^@@@STEP_TRIGGER@(.*)@@@$')
    self.assertEqual(1, subp.returncode)

  def test_shell_quote(self):
    # For regular-looking commands we shouldn't need any specialness.
    self.assertEqual(
        step_runner._shell_quote('/usr/bin/python-wrapper.bin'),
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
      quoted = step_runner._shell_quote(s)

      # We shouldn't ever get an actual newline in a command, that's awful
      # for copypasta.
      self.assertNotRegexpMatches(quoted, '\n')

      # We should be able to paste any argument into bash & zsh and get
      # exactly what subprocess did.
      bash_output = subprocess.check_output([
          'bash', '-c', '/bin/echo %s' % quoted])
      self.assertEqual(bash_output.decode('utf-8'), s + '\n')

      # zsh is untested because zsh isn't provisioned on our bots.
      # zsh_output = subprocess.check_output([
      #     'zsh', '-c', '/bin/echo %s' % quoted])
      # self.assertEqual(zsh_output.decode('utf-8'), s + '\n')

  def test_subannotations(self):
    proc = subprocess.Popen(
        self._run_cmd('step:tests/subannotations'),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    stdout, _ = proc.communicate()
    self.assertRegexpMatches(stdout, r'(?m)^!@@@BUILD_STEP@steppy@@@$')
    self.assertRegexpMatches(stdout, r'(?m)^@@@BUILD_STEP@pippy@@@$')
    # Before 'Subannotate me' we expect an extra STEP_CURSOR to reset the
    # state.
    self.assertRegexpMatches(stdout,
        r'(?m)^@@@STEP_CURSOR@Subannotate me@@@\n@@@STEP_CLOSED@@@$')



if __name__ == '__main__':
  test_env.main()
