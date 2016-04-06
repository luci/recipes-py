#!/usr/bin/env python

# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import copy
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'recipe_engine', 'third_party'))
sys.path.insert(0, ROOT_DIR)

from google import protobuf
from recipe_engine import package
from recipe_engine import package_pb2

import repo_test_util


def _updated_deps(inp, updates):
  if inp is None:
    return updates

  outp = inp.__class__()
  outp.CopyFrom(inp)
  for dep in outp.deps:
    if dep.project_id in updates:
      dep.revision = updates[dep.project_id]
  return outp


def _get_dep(inp, dep_id):
  for dep in inp.deps:
    if dep.project_id == dep_id:
      return dep
  else:
    raise Exception('Dependency %s not found in %s' % (dep, inp))


def _to_text(buf):
  return protobuf.text_format.MessageToString(buf)


def _recstrify(thing):
  if isinstance(thing, basestring):
    return str(thing)
  elif isinstance(thing, dict):
    out = {}
    for k,v in thing.iteritems():
      out[str(k)] = _recstrify(v)
    return out
  elif isinstance(thing, list):
    return map(_recstrify, thing)
  else:
    return thing


class RecipeRollError(Exception):
  def __init__(self, stdout, stderr):
    self.stdout = stdout
    self.stderr = stderr

  def __str__(self):
    return '%s:\nSTDOUT:\n%s\nSTDERR:\n%s\n' % (
        self.__class__, self.stdout, self.stderr)


class MultiRepoTest(repo_test_util.RepoTest):
  def setUp(self):
    super(MultiRepoTest, self).setUp()
    self.maxDiff = None

  def _run_roll(self, repo, expect_updates, commit=False):
    with repo_test_util.in_directory(repo['root']):
      fh, json_file = tempfile.mkstemp('.json')
      os.close(fh)

      popen = subprocess.Popen([
          'python', self._recipe_tool,
          '--package', os.path.join(repo['root'], 'infra', 'config', 'recipes.cfg'), 
          'roll',
          '--output-json', json_file],
          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      stdout, stderr = popen.communicate()

      if popen.returncode != 0:
        raise RecipeRollError(stdout, stderr)

      if expect_updates:
        self.assertRegexpMatches(stdout, r'Wrote \S*recipes.cfg')
      else:
        self.assertRegexpMatches(stdout, r'No consistent rolls found')

      if commit:
        assert expect_updates, 'Cannot commit when not expecting updates'
        git_match = re.search(r'^git commit .*', stdout, re.MULTILINE)
        self.assertTrue(git_match)
        git_command = git_match.group(0)
        subprocess.call(git_command, shell=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()
        return {
            'root': repo['root'],
            'revision': rev,
            'spec': repo['spec'],
        }

      with open(json_file, 'r') as fh:
        return json.load(fh)

  def _get_spec(self, repo):
    proto_file = package.ProtoFile(
        os.path.join(repo['root'], 'infra', 'config', 'recipes.cfg'))
    return proto_file.read()

  def test_empty_roll(self):
    repos = self.repo_setup({
      'a': [],
      'b': [ 'a' ],
    })
    self._run_roll(repos['b'], expect_updates=False)

  def test_simple_roll(self):
    repos = self.repo_setup({
      'a': [],
      'b': ['a'],
    })
    new_a = self.commit_in_repo(repos['a'])
    self._run_roll(repos['b'], expect_updates=True)
    self.assertEqual(
        _to_text(self._get_spec(repos['b'])),
        _to_text(_updated_deps(repos['b']['spec'], {
            'a': new_a['revision'],
        })))
    self._run_roll(repos['b'], expect_updates=False)

  def test_indepdendent_roll(self):
    repos = self.repo_setup({
        'b': [],
        'c': [],
        'd': ['b', 'c'],
    })
    new_b = self.commit_in_repo(repos['b'])
    new_c = self.commit_in_repo(repos['c'])
    self._run_roll(repos['d'], expect_updates=True)
    # There is no guarantee on the order the two updates come in.
    # (Usually we sort by date but these commits are within 1 second)
    # However after one roll we expect only one of the two updates to
    # have come in.
    d_spec = self._get_spec(repos['d'])
    self.assertTrue(
         (_get_dep(d_spec, 'b').revision == new_b['revision'])
      != (_get_dep(d_spec, 'c').revision == new_c['revision']))
    self._run_roll(repos['d'], expect_updates=True)
    self.assertEqual(
        _to_text(self._get_spec(repos['d'])),
        _to_text(_updated_deps(repos['d']['spec'], {
            'b': new_b['revision'],
            'c': new_c['revision'],
        })))
    self._run_roll(repos['d'], expect_updates=False)

  def test_dependent_roll(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
        'c': ['a'],
        'd': ['b', 'c'],
    })
    new_a = self.commit_in_repo(repos['a'])
    new_b = self._run_roll(repos['b'], expect_updates=True, commit=True)
    new_c = self._run_roll(repos['c'], expect_updates=True, commit=True)

    # We only expect one roll here because to roll b without c would
    # result in an inconsistent revision of a, so we should skip it.
    self._run_roll(repos['d'], expect_updates=True)
    d_spec = self._get_spec(repos['d'])
    self.assertEqual(
        _to_text(self._get_spec(repos['d'])),
        _to_text(_updated_deps(repos['d']['spec'], {
            'b': new_b['revision'],
            'c': new_c['revision'],
        })))
    self._run_roll(repos['d'], expect_updates=False)

  def test_cyclic_dependency(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    config_file = os.path.join(
        repos['a']['root'], 'infra', 'config', 'recipes.cfg')
    package.ProtoFile(config_file).write(
        package_pb2.Package(
            api_version=1,
            project_id='a',
            recipes_path='',
            deps=[
                package_pb2.DepSpec(
                    project_id='b',
                    url=repos['b']['root'],
                    branch='master',
                    revision=repos['b']['revision'],
                ),
            ],
        )
    )
    self.commit_in_repo(repos['a'])
    with self.assertRaises(RecipeRollError) as raises:
      self._run_roll(repos['b'], expect_updates=True)
    self.assertRegexpMatches(raises.exception.stderr, 'CyclicDependencyError')

  def test_output_json_simple(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    new_a = self.commit_in_repo(
        repos['a'], message='Did I do good', author_name='P Diddy',
        author_email='diddyp@facebook.google')

    output = self._run_roll(repos['b'], expect_updates=True)
    self.assertEqual(output, {
        'updates': [
            {
                'author': 'diddyp@facebook.google',
                'revision': new_a['revision'],
                'repo_id': 'a',
                'message': 'Did I do good',
            }
        ]
    })

  def test_output_json_skipped(self):
    """Tests that commit infos are accumulated when multiple rolls happen at
    once due to inconsistent dependencies."""
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
        'c': ['a'],
        'd': ['b','c'],
    })

    self.commit_in_repo(repos['a'], message='A commit',
                         author_email='scrapdaddy@serious.music')
    self._run_roll(repos['b'], expect_updates=True)
    b_roll = self.commit_in_repo(repos['b'], message='B roll',
                         author_email='barkdoggy@serious.music')
    c_commit = self.commit_in_repo(repos['c'], message='C commit',
                         author_email='swimfishy@serious.music')
    self._run_roll(repos['c'], expect_updates=True,)
    c_roll = self.commit_in_repo(repos['c'], message='C roll',
                         author_email='herpderply@slurp.flurpy')

    output = self._run_roll(repos['d'], expect_updates=True)
    self.assertEqual(output, {
        'updates': [
            {
                'message': 'B roll',
                'author': 'barkdoggy@serious.music',
                'revision': b_roll['revision'],
                'repo_id': 'b',
            }, {
                'message': 'C commit',
                'author': 'swimfishy@serious.music',
                'revision': c_commit['revision'],
                'repo_id': 'c',
            }, {
                'message': 'C roll',
                'author': 'herpderply@slurp.flurpy',
                'revision': c_roll['revision'],
                'repo_id': 'c',
            }
        ]
    })
    self._run_roll(repos['d'], expect_updates=False)

  def test_roll_recipe_dir_only(self):
    """Tests that changes that do not affect the recipes subdir of a repo
    are not rolled."""

    repos = {}
    repos['a'] = self.create_repo('a', package_pb2.Package(
        api_version=1,
        project_id='a',
        recipes_path='foorecipes',
        deps=[],
    ))
    repos['b'] = self.create_repo('b', package_pb2.Package(
        api_version=1,
        project_id='b',
        recipes_path='',
        deps=[
            package_pb2.DepSpec(
                project_id='a',
                url=repos['a']['root'],
                branch='master',
                revision=repos['a']['revision'],
            )
        ],
    ))

    with open(os.path.join(repos['a']['root'], 'some_file'), 'w') as fh:
      fh.write('Some irrelevant things')
    with repo_test_util.in_directory(repos['a']['root']):
      subprocess.check_output(['git', 'add', 'some_file'])
      subprocess.check_output(['git', 'commit', '-m', 'Irrelevant commit'])

    self._run_roll(repos['b'], expect_updates=False)

  def test_duplicate_names(self):
    repos = self.repo_setup({
        'a': [],
        'b': ['a'],
    })
    fname = lambda repo, *f: os.path.join(repos[repo]['root'], *f)

    for repo in ('a', 'b'):
      os.makedirs(fname(repo, 'recipe_modules', 'foo'))

      with open(
          fname(repo, 'recipe_modules', 'foo', '__init__.py'), 'w') as fh:
        fh.write("DEPS = []")

      with open(
          fname(repo, 'recipe_modules', 'foo', 'api.py'), 'w') as fh:
        fh.writelines([
          'from recipe_engine import recipe_api\n',
          '\n',
          'class FakeApi(recipe_api.RecipeApi):\n',
          '  pass\n',
        ])

      with repo_test_util.in_directory(fname(repo)):
        subprocess.check_output(['git', 'add', 'recipe_modules'])
        subprocess.check_output(['git', 'commit', '-m', 'Add the files'])


    os.makedirs(os.path.join(repos['b']['root'], 'recipes'))
    with open(
        os.path.join(
            repos[repo]['root'], 'recipes', 'test.py'), 'w') as fh:
      fh.writelines([
        'DEPS = {\n',
        '  "foo": "a/foo",\n',
        '  "otherfoo": "foo"\n',
        '}\n',
        '\n',
        'def RunSteps(api):\n',
        '  pass\n',
      ])
    self._run_roll(repos['b'], expect_updates=True)

    popen = subprocess.Popen([
        'python', self._recipe_tool,
        '--package', os.path.join(
            repos['b']['root'], 'infra', 'config', 'recipes.cfg'),
        'run', 'test'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = popen.communicate()
    self.assertEqual(popen.returncode, 0, stderr)

if __name__ == '__main__':
  unittest.main()
