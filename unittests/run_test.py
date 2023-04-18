#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import print_function
from future.utils import iteritems

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

from parameterized import parameterized, parameterized_class

import test_env

from recipe_engine.internal.engine import _shell_quote

from recipe_engine.third_party import luci_context

# prevent LUCI_CONTEXT leakage :)
os.environ.pop(luci_context.ENV_KEY, None)


class RunTest(test_env.RecipeEngineUnitTest):
  @parameterized.expand(
    [('py2', False), ('py3', True)],
    name_func=lambda func, _, param: '%s_%s' % (func.__name__, param.args[0]),
  )
  def test_run(self, _, py3):
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

    output, retcode = deps.main_repo.recipes_py('-v', '-v', 'run', 'my_recipe',
                                                py3=py3)
    self.assertEqual(retcode, 0,
                     'ret code is not zero. Recipe output\n%s' % output)

  def test_run_incomplete_deps(self):
    deps = self.FakeRecipeDeps()

    a = deps.add_repo('a', detached=True)
    a.commit('a something')

    b = deps.add_repo('b', detached=True)
    b.commit('b something')

    a.add_dep('b')
    a.commit('add b dep')

    deps.main_repo.add_dep('a')
    a.commit('add a dep')

    output, retcode = deps.main_repo.recipes_py('fetch')
    self.assertEqual(retcode, 1)
    self.assertIn('Repo \'a\' depends on [\'b\'], which is missing', output)

  def test_run_circular_deps(self):
    deps = self.FakeRecipeDeps()

    a = deps.add_repo('a', detached=True)
    a.commit('a something')

    a.add_dep('main')
    a.commit('add main dep')

    deps.main_repo.add_dep('a')
    a.commit('add a dep')

    output, retcode = deps.main_repo.recipes_py('fetch')
    self.assertEqual(retcode, 1)
    self.assertIn(
        'Dependency \'a\' has circular dependency on \'main\'', output)


class RunSmokeTest(test_env.RecipeEngineUnitTest):
  def _run_cmd(self, recipe, workdir, properties=None, engine_args=()):
    script_path = os.path.join(test_env.ROOT_DIR, 'recipes.py')

    proplist = [
      '%s=%s' % (k, json.dumps(v)) for k, v in iteritems(properties or {})
    ]

    return (
      ['python', script_path] +
      list(engine_args) +
      ['run', '--workdir', workdir, recipe] +
      proplist
    )

  def _test_recipe(self, recipe, properties=None, env=None):
    workdir = tempfile.mkdtemp(prefix='recipe_engine_run_test-')
    try:
      proc = subprocess.Popen(
          self._run_cmd(recipe, workdir, properties),
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
          env=env)
      stdout = proc.communicate()
      self.assertEqual(0, proc.returncode, '%d != %d when testing %s:\n%s' % (
          0, proc.returncode, recipe, stdout))
    finally:
      shutil.rmtree(workdir, ignore_errors=True)

  def test_examples(self):
    env = os.environ.copy()

    # Set the "RECIPE_ENGINE_CONTEXT_TEST" environment variable to a known
    # value, "default". This is used by the "context:tests/env" recipe module
    # as a basis for runtime tests.
    env['RECIPE_ENGINE_CONTEXT_TEST'] = 'default'

    tests = [
      ['context:examples/full'],
      ['context:tests/env'],
      ['file:examples/copy'],
      ['file:examples/copytree'],
      ['file:examples/glob'],
      ['futures:examples/lazy_fan_out_in'],
      ['json:examples/full'],
      ['path:examples/full'],
      ['raw_io:examples/full'],
      ['step:examples/full'],

      ['engine_tests/functools_partial'],
    ]
    for test in tests:
      print("running", test)
      self._test_recipe(*test, env=env)

  def test_bad_subprocess(self):
    now = time.time()
    self._test_recipe('engine_tests/bad_subprocess')
    after = time.time()

    # Test has a daemon that holds on to stdout for 30s, but the daemon's parent
    # process (e.g. the one that recipe engine actually runs) quits immediately.
    # If this takes longer than 20 seconds to run (there can be overhead in
    # running the engine/cipd/protoc/etc.), we consider it failed.
    #
    # 20 seconds is because the trybots typically peg all processors, leading to
    # bugs like crbug.com/1434371. 20 should (in theory) be enough to avoid
    # timing issues like this, but sill effectively test this functionality.
    self.assertLess(after - now, 20)

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


@parameterized_class(
  [{"py_version": 2}, {"py_version": 3}],
  class_name_func=(
    lambda cls, _, params: '%s_PY%d' % (cls.__name__, params['py_version'])),
)
class LuciexeSmokeTest(test_env.RecipeEngineUnitTest):
  def _wait_for_file(self, filename, duration):
    begin = time.time()
    while True:
      self.assertLessEqual(time.time() - begin, duration,
                           'took too long to find ' + filename)
      try:
        with open(filename, 'r') as f:
          return f.read()
      except IOError:
        time.sleep(.5)

  @contextlib.contextmanager
  def _run_bbagent(self, properties, grace_period=30):
    workdir = tempfile.mkdtemp(prefix='recipe_engine_run_test-')
    proc = None
    try:
      pidfile = os.path.join(workdir, 'pidfile')
      fake_bbagent = os.path.join(test_env.ROOT_DIR, 'misc', 'fake_bbagent.sh')

      env = os.environ.copy()
      env.pop(luci_context.ENV_KEY, None)
      env['WD'] = workdir
      env['LUCI_GRACE_PERIOD'] = str(grace_period)
      if self.py_version == 3:
        env['RECIPES_USE_PY3'] = 'true'

      proc = subprocess.Popen(
          [fake_bbagent, "--pid-file", pidfile],
          stdin=subprocess.PIPE,
          env=env)
      proc.stdin.write(json.dumps({
        "input": {
          "properties": properties,
        },
      }))
      proc.stdin.close()

      engine_pid = int(self._wait_for_file(pidfile, 30).strip())

      yield proc, engine_pid
    finally:
      if proc and proc.poll() is None:
        proc.kill()
      shutil.rmtree(workdir, ignore_errors=True)

  def _test_bbagent(self, properties, grace_period=30, timeout=30):
    scrap = tempfile.mkdtemp(prefix='recipe_engine_run_test-')
    try:
      wd = os.path.join(scrap, 'wd')
      os.mkdir(wd)

      outfile = os.path.join(scrap, 'final_build.json')
      pidfile = os.path.join(wd, 'pidfile')
      fake_bbagent = os.path.join(test_env.ROOT_DIR, 'misc', 'fake_bbagent.sh')

      deadline = time.time() + timeout

      env = os.environ.copy()
      env.pop(luci_context.ENV_KEY, None)
      env['WD'] = wd
      env['LUCI_GRACE_PERIOD'] = str(grace_period)
      env['LUCI_SOFT_DEADLINE'] = str(deadline)
      env['FAKE_BBAGENT_OUTFILE'] = outfile
      if self.py_version == 3:
        env['RECIPES_USE_PY3'] = 'true'
      proc = subprocess.Popen(
          [fake_bbagent, "--pid-file", pidfile],
          stdin=subprocess.PIPE,
          env=env)

      proc.stdin.write(json.dumps({
        "input": {
          "properties": properties,
        },
      }))
      proc.stdin.close()

      engine_pid = int(self._wait_for_file(pidfile, 30).strip())
      did_soft_deadline = False

      while True:
        if proc.poll() is not None:
          with open(os.path.join(wd, 'logs', 'stderr')) as log:
            print()
            print("Raw engine logs:")
            sys.stdout.write(log.read())
          with open(outfile) as of:
            bpdata = of.read()
            print()
            print("Final build.proto:")
            sys.stdout.write(bpdata)
            return json.loads(bpdata)

        if deadline and time.time() > deadline:
          if not did_soft_deadline:
            print("Hit soft deadline")
            did_soft_deadline = True
            os.kill(engine_pid, signal.SIGTERM)
            deadline += grace_period
          else:
            print("Hit hard deadline")
            os.kill(engine_pid, signal.SIGKILL)
            deadline = None

        time.sleep(1)

    finally:
      shutil.rmtree(scrap, ignore_errors=True)

  def test_early_terminate(self):
    scrap = tempfile.mkdtemp(prefix='recipe_engine-run_test-scrap-')
    try:
      # The recipe will make a bunch of subprocesses which will touch this
      # about once per second.
      output_touchfile = os.path.join(scrap, 'output_touchfile')
      running_touchfile = os.path.join(scrap, 'running_touchfile')

      props = {
        'recipe': 'engine_tests/early_termination',
        'output_touchfile': output_touchfile,
        'running_touchfile': running_touchfile,
      }
      with self._run_bbagent(props, grace_period=5) as (proc, engine_pid):
        # Wait up to 20s for the recipe to indicate that it launched all its
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

  def test_add_build_tags(self):
    final_build = self._test_bbagent(
        {'recipe': 'buildbucket:tests/add_build_tags'},
    )
    self.assertListEqual(
      sorted(final_build['tags'], key=lambda tag: (tag['key'], tag['value'])),
      [
        {'key': 'hide-in-gerrit', 'value': 'pointless'},
        {'key': 'k1', 'value': 'v1'},
        {'key': 'k2', 'value': 'v2'},
        {'key': 'k2', 'value': 'v2_1'},
      ],
    )

  def test_add_step_tags(self):
    final_build = self._test_bbagent(
        {'recipe': 'buildbucket:tests/add_step_tags'},
    )
    for step in final_build['steps']:
      if step["name"] == "hostname":
        self.assertListEqual(
          sorted(step.get('tags'), key=lambda tag: (tag['key'], tag['value'])),
          [
            {'key': 'k1', 'value': 'v1'},
            {'key': 'k2', 'value': 'v2'},
          ],
        )

  def test_output_gitiles(self):
    final_build = self._test_bbagent(
        {'recipe': 'buildbucket:tests/output_commit'},
    )
    self.assertDictEqual(final_build['output']['gitiles_commit'], {
      'host': 'chromium.googlesource.com',
      'id': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'position': 42,
      'project': 'infra/infra',
      'ref': 'refs/heads/main',
    })

  def test_proto_output_properties(self):
    final_build = self._test_bbagent(
        {'recipe': 'engine_tests/proto_output_properties'},
    )
    output_props = final_build['output']['properties']
    self.assertDictEqual(output_props['$mod/proto_out'], {
      'str': 'foo',
      'strs': ['bar', 'baz'],
      'msg' : {
        'num': 1,
        'nums': [10, 11, 12],
      },
    })

  def test_external_timeout(self):
    final_build = self._test_bbagent(
        {'recipe': 'engine_tests/long_sleep'},
        timeout=10,
    )
    for step in final_build['steps']:
      del step['end_time']
      del step['logs']
      del step['start_time']
      if step['name'] == 'setup_build':
        del step['summary_markdown']
    self.assertDictEqual(final_build, {
      'status': 'CANCELED',
      'summary_markdown': (
        "Infra Failure: Step('sleep forever') (canceled) (retcode: -15)"),
      'steps': [
        {'name': 'setup_build', 'status': 'SUCCESS'},
        {'name': 'sleep a bit', 'status': 'FAILURE'},
        {'name': 'sleep forever', 'status': 'CANCELED'},
      ],
    })

  def test_external_timeout_recovery(self):
    final_build = self._test_bbagent(
        {
          'recipe': 'engine_tests/long_sleep',
          'recover': True,
        },
        timeout=10,
    )
    self.assertEqual(final_build['status'], 'SUCCESS')

  def test_nonexistent_command(self):
    final_build = self._test_bbagent(
      {'recipe': 'engine_tests/nonexistent_command'},
    )
    self.assertEqual(final_build['status'], 'SUCCESS')


if __name__ == '__main__':
  test_env.main()
