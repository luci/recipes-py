#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import test_env

from recipe_engine.internal.engine import _shell_quote

from recipe_engine.third_party import luci_context

# prevent LUCI_CONTEXT leakage :)
os.environ.pop(luci_context.ENV_KEY, None)


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

  def _wait_for_file(self, filename, duration):
    begin = time.time()
    while True:
      self.assertLessEqual(time.time() - begin, duration,
                           'took too long to find ' + filename)
      try:
        with open(filename, 'r') as f:
          return f.read()
      except IOError as ex:
        print >>sys.stderr, "nerp", ex
        time.sleep(.5)

  @contextlib.contextmanager
  def _run_bbagent(self, properties, grace_period=30):
    workdir = tempfile.mkdtemp(prefix='recipe_engine_run_test-')
    pidfile = os.path.join(workdir, 'pidfile')
    fake_bbagent = os.path.join(test_env.ROOT_DIR, 'misc', 'fake_bbagent.sh')

    env = os.environ.copy()
    env.pop(luci_context.ENV_KEY, None)
    env['WD'] = workdir
    env['LUCI_GRACE_PERIOD'] = str(grace_period)
    proc = subprocess.Popen(
        [fake_bbagent, "--pid-file", pidfile],
        stdin=subprocess.PIPE,
        env=env)

    try:
      proc.stdin.write(json.dumps({
        "input": {
          "properties": properties,
        },
      }))
      proc.stdin.close()

      engine_pid = int(self._wait_for_file(pidfile, 20).strip())

      yield proc, engine_pid
    finally:
      if proc.poll() is None:
        proc.kill()
      shutil.rmtree(workdir, ignore_errors=True)

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
    # If this takes longer than 10 seconds to run (there can be overhead in
    # running the engine/cipd/protoc/etc.), we consider it failed.
    self.assertLess(after - now, 10)

  def test_early_terminate(self):
    scrap = tempfile.mkdtemp(prefix='recipe_engine-run_test-scrap-')
    try:
      # The recipe will make a bunch of subprocesses which whill touch this
      # every ~second.
      output_touchfile = os.path.join(scrap, 'output_touchfile')
      running_touchfile = os.path.join(scrap, 'running_touchfile')

      props = {
        'recipe': 'engine_tests/early_termination',
        'output_touchfile': output_touchfile,
        'running_touchfile': running_touchfile,
      }
      with self._run_bbagent(props, grace_period=5) as (proc, engine_pid):
        # Wait up to 10s for the recipe to indicate that it launched all its
        # subprocesses.
        self._wait_for_file(running_touchfile, 20)

        # Ok, the recipe is all up and running now. Let's give the command
        # a poke and wait for a bit.
        os.kill(engine_pid, signal.SIGTERM)

        # from this point the recipe should teardown in ~5s. We give it 10 to
        # be generous.
        time.sleep(10)
        self.assertIsNotNone(proc.poll())

        # sample the output_touchfile
        mtime = os.stat(output_touchfile).st_mtime
        # now wait a bit to see if anything's still touching it
        time.sleep(5)
        self.assertEqual(mtime, os.stat(output_touchfile).st_mtime)
    finally:
      shutil.rmtree(scrap, ignore_errors=True)


  def test_nonexistent_command(self):
    subp = subprocess.Popen(
        self._run_cmd('engine_tests/nonexistent_command'),
        stdout=subprocess.PIPE)
    stdout, _ = subp.communicate()

    self.assertRegexpMatches(stdout, '(?m)^@@@STEP_EXCEPTION@@@$')
    self.assertRegexpMatches(stdout, 'failed to resolve cmd0')
    self.assertEqual(1, subp.returncode, stdout)

  def test_shell_quote(self):
    # For regular-looking commands we shouldn't need any specialness.
    self.assertEqual(
        _shell_quote('/usr/bin/python-wrapper.bin'),
        '/usr/bin/python-wrapper.bin')

    STRINGS = [
        'Simple.Command123/run',
        'Command with spaces',
        'Command with "quotes"',
        "I have 'single quotes'",
        'Some \\Esc\ape Seque\nces/',
        u'Unicode makes me \u2609\u203f\u2299'.encode('utf-8'),
    ]

    for s in STRINGS:
      quoted = _shell_quote(s)

      # We shouldn't ever get an actual newline in a command, that's awful
      # for copypasta.
      self.assertNotRegexpMatches(quoted, '\n')

      # We should be able to paste any argument into bash & zsh and get
      # exactly what subprocess did.
      bash_output = subprocess.check_output([
          'bash', '-c', '/bin/echo %s' % quoted])
      self.assertEqual(bash_output, s + '\n')

      # zsh is untested because zsh isn't provisioned on our bots.
      # zsh_output = subprocess.check_output([
      #     'zsh', '-c', '/bin/echo %s' % quoted])
      # self.assertEqual(zsh_output.decode('utf-8'), s + '\n')



if __name__ == '__main__':
  test_env.main()
