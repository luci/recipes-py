#!/usr/bin/env vpython
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import subprocess

import attr
import mock

import test_env

from recipe_engine.internal import fetch, exceptions
from recipe_engine.internal.simple_cfg import \
  SimpleRecipesCfg, RECIPES_CFG_LOCATION_REL


CPE = subprocess.CalledProcessError
IRC = RECIPES_CFG_LOCATION_REL

FETCH_MOD = fetch.__name__

class NoMoreExpectatedCalls(ValueError):
  pass


def multi(*side_effect_funcs):
  l = len(side_effect_funcs)
  it = iter(side_effect_funcs)
  def _inner(*args, **kwargs):
    try:
      return it.next()(*args, **kwargs)
    except StopIteration:
      raise NoMoreExpectatedCalls(
        'multi() ran out of values (i=%d): f(*%r, **%r)' % (l, args, kwargs))
  return _inner


class TestGit(test_env.RecipeEngineUnitTest):

  def setUp(self):
    super(TestGit, self).setUp()
    fetch.Backend._GIT_METADATA_CACHE = {}
    mock.patch(fetch.__name__+'.GitBackend.GIT_BINARY', 'GIT').start()
    self.addCleanup(mock.patch.stopall)

  def assertMultiDone(self, mocked_call):
    with self.assertRaises(NoMoreExpectatedCalls):
      mocked_call()

  def g(self, args, data_or_exception=''):
    full_args = ['GIT']
    if args[0] != 'init':  # init is special
      full_args += ['-c', 'advice.detachedHead=false']
    full_args += args

    if isinstance(data_or_exception, Exception):
      def _inner(*real_args):
        self.assertListEqual(list(real_args), full_args)
        raise data_or_exception
    else:
      def _inner(*real_args):
        self.assertListEqual(list(real_args), full_args)
        return data_or_exception
    return _inner

  @property
  def default_spec(self):
    return SimpleRecipesCfg.from_dict({
      'api_version': 2,
      'repo_name': 'main',
      'deps': {
        'recipe_engine': {
          'url': 'https://test.example.com/recipe_engine.git',
          'branch': 'refs/heads/master',
          'revision': 'b'*40,
        }
      }
    })

  def g_metadata_calls(self, dirname='dir', commit='a'*40,
                       email='foo@example.com', msg='hello\nworld',
                       commit_timestamp=1492131405, config=None,
                       diff=('foo', 'bar')):
    config = config or self.default_spec

    return [
      self.g([
        '-C', dirname, 'show', '-s', '--format=%aE%n%ct%n%B', commit
      ], '%s\n%d\n%s\n' % (email, commit_timestamp, msg)),
      self.g([
        '-C', dirname, 'cat-file', 'blob', commit+':'+IRC
      ], json.dumps(config.asdict())),
      self.g([
        '-C', dirname,
        'diff-tree', '-r', '--no-commit-id', '--name-only', commit+'^!',
      ], '\n'.join(diff))
    ]

  def g_ls_remote(self):
    return self.g(['-C', 'dir', 'ls-remote', 'repo', 'revision'],
                  'a'*40 + '\trevision')

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_fresh_clone(self, git, isdir):
    isdir.return_value = False
    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote(),
    ] + self.g_metadata_calls() + [
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40], CPE('', 1)),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'a'*40])
    ]))

    fetch.GitBackend('dir', 'repo').checkout('revision')

    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_existing_checkout(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(*([
      self.g_ls_remote(),
    ] + self.g_metadata_calls() + [
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40], CPE('', 1)),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'a'*40])
    ]))

    fetch.GitBackend('dir', 'repo').checkout('revision')

    self.assertMultiDone(git)
    isdir.assert_has_calls([
      mock.call('dir/.git'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_existing_checkout_same_revision(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(*([
      self.g_ls_remote(),
    ] + self.g_metadata_calls() + [
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40]),
    ]))

    fetch.GitBackend('dir', 'repo').checkout('revision')

    self.assertMultiDone(git)
    isdir.assert_has_calls([
      mock.call('dir/.git'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_unclean_filesystem(self, git, isdir):
    isdir.return_value = False
    def _mock_execute(*_args):
      raise CPE(1, 'bad stuff')
    git.side_effect = _mock_execute

    with self.assertRaises(exceptions.GitFetchError):
      fetch.GitBackend('dir', 'repo').checkout('revision')

    git.assert_called_once_with('GIT', 'init', 'dir')

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_rev_parse_fail(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(*(
      self.g_ls_remote(),

      self.g(
        ['-C', 'dir', 'show', '-s', '--format=%aE%n%ct%n%B', 'a'*40],
        CPE(1, 'nope')),

      self.g(['-C', 'dir', 'fetch', 'repo', 'revision']),
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40], CPE('', 1)),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'a'*40]),
    ))

    fetch.GitBackend('dir', 'repo').checkout('revision')

    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_commit_metadata_empty_recipes_path(self, git, isdir):
    isdir.return_value = False
    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote(),
    ] + self.g_metadata_calls()))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = self.default_spec,
      roll_candidate = True,
    ))
    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  @mock.patch(fetch.__name__+'.gitattr_checker.AttrChecker.check_files')
  def test_commit_metadata_not_interesting(self, attr_checker, git, isdir):
    attr_checker.side_effect = [False]
    isdir.return_value = False
    spec = attr.evolve(self.default_spec, recipes_path='recipes')

    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote(),
    ] + self.g_metadata_calls(config=spec)))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = spec,
      roll_candidate = False,
    ))
    self.assertMultiDone(git)
    attr_checker.assert_called_with('a'*40, set(['foo', 'bar']))

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_commit_metadata_IRC_change(self, git, isdir):
    isdir.return_value = False
    spec = attr.evolve(self.default_spec, recipes_path='recipes')

    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote(),
    ] + self.g_metadata_calls(config=spec, diff=tuple([IRC]))))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = spec,
      roll_candidate = True,
    ))
    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_commit_metadata_recipes_change(self, git, isdir):
    isdir.return_value = False
    spec = attr.evolve(self.default_spec, recipes_path='recipes')

    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote()
    ] + self.g_metadata_calls(config=spec, diff=tuple(['recipes/foo']))))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = spec,
      roll_candidate = True,
    ))
    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  @mock.patch(fetch.__name__+'.gitattr_checker.AttrChecker.check_files')
  def test_commit_metadata_tagged_change(self, attr_checker, git, isdir):
    attr_checker.side_effect = [True]
    isdir.return_value = False
    spec = attr.evolve(self.default_spec, recipes_path='recipes')

    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote()
    ] + self.g_metadata_calls(config=spec)))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = spec,
      roll_candidate = True,
    ))
    self.assertMultiDone(git)
    attr_checker.assert_called_with('a'*40, set(['foo', 'bar']))

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_commit_metadata_only_gitattributes_file(self, git, isdir):
    isdir.return_value = False
    spec = attr.evolve(self.default_spec, recipes_path='recipes')

    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote()
    ] + self.g_metadata_calls(config=spec, diff=['.gitattributes'])))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = spec,
      roll_candidate = True,
    ))
    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch(fetch.__name__+'.GitBackend._execute')
  def test_commit_metadata_only_gitattributes_file_2(self, git, isdir):
    isdir.return_value = False
    spec = attr.evolve(self.default_spec, recipes_path='recipes')

    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g_ls_remote()
    ] + self.g_metadata_calls(config=spec, diff=['subdir/.gitattributes'])))

    result = fetch.GitBackend('dir', 'repo').commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = spec,
      roll_candidate = True,
    ))
    self.assertMultiDone(git)


if __name__ == '__main__':
  test_env.main()
