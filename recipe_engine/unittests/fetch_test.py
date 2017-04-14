#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
import itertools
import json
import unittest

import test_env

import mock
import subprocess42

from recipe_engine import fetch
from recipe_engine import package_pb2
from recipe_engine import requests_ssl


CPE = subprocess42.CalledProcessError


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


class TestGit(unittest.TestCase):

  def setUp(self):
    fetch.Backend._GIT_METADATA_CACHE = {}

    self._patchers = [
      mock.patch('recipe_engine.fetch.GitBackend._GIT_BINARY', 'GIT'),
    ]
    for p in self._patchers:
      p.start()

  def tearDown(self):
    for p in reversed(self._patchers):
      p.stop()

  def assertMultiDone(self, mocked_call):
    with self.assertRaises(NoMoreExpectatedCalls):
      mocked_call()

  def g(self, args, data_or_exception=''):
    full_args = ['GIT'] + args

    if isinstance(data_or_exception, Exception):
      def _inner(*real_args):
        self.assertListEqual(list(real_args), full_args)
        raise data_or_exception
    else:
      def _inner(*real_args):
        self.assertListEqual(list(real_args), full_args)
        return data_or_exception
    return _inner

  def g_metadata_calls(self, dirname='dir', commit='a'*40,
                       email='foo@example.com', msg='hello\nworld',
                       commit_timestamp=1492131405, config=None):
    config = config or {'api_version': 2}

    return [
      self.g([
        '-C', dirname, 'show', '-s', '--format=%aE%n%ct%n%B', commit
      ], '%s\n%d\n%s\n' % (email, commit_timestamp, msg)),
      self.g([
        '-C', dirname, 'cat-file', 'blob', commit+':infra/config/recipes.cfg'
      ], json.dumps(config))
    ]

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_fresh_clone(self, git, isdir):
    isdir.return_value = False
    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g(['-C', 'dir',  'ls-remote', 'repo', 'revision'], 'a'*40),
    ] + self.g_metadata_calls() + [
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40], CPE('', 1)),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'a'*40])
    ]))

    fetch.GitBackend('dir', 'repo', True).checkout('revision')

    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_existing_checkout(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(*([
      self.g(['-C', 'dir', 'ls-remote', 'repo', 'revision'], 'a'*40)
    ] + self.g_metadata_calls() + [
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40], CPE('', 1)),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'a'*40])
    ]))

    fetch.GitBackend('dir', 'repo', True).checkout('revision')

    self.assertMultiDone(git)
    isdir.assert_has_calls([
      mock.call('dir/.git'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_existing_checkout_same_revision(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(*([
      self.g(['-C', 'dir', 'ls-remote', 'repo', 'revision'], 'a'*40)
    ] + self.g_metadata_calls() + [
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40]),
    ]))

    fetch.GitBackend('dir', 'repo', True).checkout('revision')

    self.assertMultiDone(git)
    isdir.assert_has_calls([
      mock.call('dir/.git'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_clone_not_allowed(self, _git, isdir):
    isdir.return_value = True
    with self.assertRaises(fetch.FetchNotAllowedError):
      fetch.GitBackend('dir', 'repo', False).checkout('revision')

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_unclean_filesystem(self, git, isdir):
    isdir.return_value = False
    def _mock_execute(*_args):
      raise subprocess42.CalledProcessError(1, 'bad stuff')
    git.side_effect = _mock_execute

    with self.assertRaises(fetch.GitError):
      fetch.GitBackend('dir', 'repo', False).checkout('revision')

    git.assert_called_once_with('GIT', 'init', 'dir')

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_rev_parse_fail(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(*(
      self.g(['-C', 'dir', 'ls-remote', 'repo', 'revision'], 'a'*40),

      self.g(
        ['-C', 'dir', 'show', '-s', '--format=%aE%n%ct%n%B', 'a'*40],
        CPE(1, 'nope')),

      self.g(['-C', 'dir', 'fetch', 'repo', 'revision']),
      self.g(['-C', 'dir', 'diff', '--quiet', 'a'*40], CPE('', 1)),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'a'*40]),
    ))

    fetch.GitBackend('dir', 'repo', True).checkout('revision')

    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_rev_parse_fetch_not_allowed(self, git, isdir):
    isdir.return_value = True
    with self.assertRaises(fetch.FetchNotAllowedError):
      fetch.GitBackend('dir', 'repo', False).checkout('revision')
    isdir.assert_has_calls([
      mock.call('dir/.git'),
    ])
    self.assertFalse(git.called)

  @mock.patch('recipe_engine.fetch.GitBackend._execute')
  def test_commit_metadata(self, git):
    git.side_effect = multi(*([
      self.g(['init', 'dir']),
      self.g(['-C', 'dir', 'ls-remote', 'repo', 'revision'], 'a'*40),
    ] + self.g_metadata_calls()))

    result = fetch.GitBackend('dir', 'repo', True).commit_metadata('revision')
    self.assertEqual(result, fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('hello', 'world'),
      spec = package_pb2.Package(api_version=2)
    ))
    self.assertMultiDone(git)


class TestGitiles(unittest.TestCase):
  def setUp(self):
    requests_ssl.disable_check()
    fetch.Backend._GIT_METADATA_CACHE = {}
    fetch.GitilesBackend._COMMIT_JSON_CACHE = {}

    self.proto_text = u"""{
  "api_version": 2,
  "project_id": "foo",
  "recipes_path": "path/to/recipes"
}""".lstrip()

    self.a = 'a'*40
    self.a_dat = {
      'commit': self.a,
      'author': {'email': 'foo@example.com'},
      'committer': {'time': 'Fri Apr 14 00:56:45 2017'},
      'message': 'message',
    }

    self.a_meta = fetch.CommitMetadata(
      revision = 'a'*40,
      author_email = 'foo@example.com',
      commit_timestamp = 1492131405,
      message_lines = ('message',),
      spec = package_pb2.Package(
        api_version = 2,
        project_id = 'foo',
        recipes_path = 'path/to/recipes',
      )
    )

  def assertMultiDone(self, mocked_call):
    with self.assertRaises(NoMoreExpectatedCalls):
      mocked_call()

  def j(self, url, data, status_code=200):
    """Mock a request.get to return json data."""
    return self.r(url, u')]}\'\n'+json.dumps(data), status_code)

  def d(self, url, data, status_code=200):
    """Mock a request.get to return base64 encoded data."""
    return self.r(url, data.encode('base64'), status_code)

  def r(self, url, data_or_exception, status_code=200):
    """Mock a request.get to return raw data."""
    if isinstance(data_or_exception, Exception):
      def _inner(got_url, *args, **kwargs):
        self.assertFalse(args)
        self.assertFalse(kwargs)
        self.assertEqual(got_url, url)
        raise data_or_exception
    else:
      def _inner(got_url, *args, **kwargs):
        self.assertFalse(args)
        self.assertFalse(kwargs)
        self.assertEqual(got_url, url)
        return mock.Mock(
          text=data_or_exception,
          content=data_or_exception,
          status_code=status_code)
    return _inner

  @mock.patch('__builtin__.open', mock.mock_open())
  @mock.patch('shutil.rmtree')
  @mock.patch('os.makedirs')
  @mock.patch('tarfile.open')
  @mock.patch('requests.get')
  def test_checkout(self, requests_get, _tarfile_open, makedirs, rmtree):
    requests_get.side_effect = multi(
      self.j('repo/+/revision?format=JSON', self.a_dat),
      self.j('repo/+/%s?format=JSON' % self.a, self.a_dat),
      self.d('repo/+/%s/infra/config/recipes.cfg?format=TEXT' % self.a,
             self.proto_text),
      self.d('repo/+archive/%s/path/to/recipes.tar.gz' % self.a, ''),
    )

    fetch.GitilesBackend('dir', 'repo', True).checkout('revision')

    makedirs.assert_has_calls([
      mock.call('dir/infra/config'),
      mock.call('dir/path/to/recipes'),
    ])

    rmtree.assert_called_once_with('dir', ignore_errors=True)
    self.assertMultiDone(requests_get)

  @mock.patch('requests.get')
  def test_updates(self, requests_get):
    sha_a = 'a'*40
    sha_b = 'b'*40
    log_json = {
      'log': [
        {
          'commit': sha_b,
          'author': {'email': 'foo@example.com'},
          'committer': {'time': 'Fri Apr 14 00:58:45 2017'},
          'message': 'message',
          'tree_diff': [
            {
              'old_path': '/dev/null',
              'new_path': 'path1/foo',
            },
          ],
        },
        {
          'commit': 'def456',
          'author': {'email': 'foo@example.com'},
          'committer': {'time': 'Fri Apr 14 00:57:45 2017'},
          'message': 'message',
          'tree_diff': [
            {
              'old_path': '/dev/null',
              'new_path': 'path8/foo',
            },
          ],
        },
        {
          'commit': sha_a,
          'author': {'email': 'foo@example.com'},
          'committer': {'time': 'Fri Apr 14 00:56:45 2017'},
          'message': 'message',
          'tree_diff': [
            {
              'old_path': '/dev/null',
              'new_path': 'path8/foo',
            },
            {
              'old_path': 'path2/foo',
              'new_path': '/dev/null',
            },
          ],
        },
      ],
    }

    requests_get.side_effect = multi(
      self.j('repo/+/reva?format=JSON', {
        'commit': sha_a,
        'author': {'email': 'foo@example.com'},
        'committer': {'time': 'Fri Apr 14 00:56:45 2017'},
        'message': 'message',
      }),
      self.j('repo/+/revb?format=JSON', {
        'commit': sha_b,
        'author': {'email': 'foo@example.com'},
        'committer': {'time': 'Fri Apr 14 00:58:45 2017'},
        'message': 'message',
      }),
      self.j('repo/+log/%s..%s?name-status=1&format=JSON' % (sha_a, sha_b),
             log_json),
      self.d('repo/+/%s/infra/config/recipes.cfg?format=TEXT' % sha_a,
             self.proto_text),
      self.d('repo/+/%s/infra/config/recipes.cfg?format=TEXT' % sha_b,
             self.proto_text),
    )

    be = fetch.GitilesBackend('dir', 'repo', True)
    self.assertEqual(sha_a, be.resolve_refspec('reva'))
    self.assertEqual(sha_b, be.resolve_refspec('revb'))

    self.assertEqual(
        [self.a_meta,
         fetch.CommitMetadata(
          revision = sha_b,
          author_email = 'foo@example.com',
          commit_timestamp = 1492131525,
          message_lines = ('message',),
          spec = package_pb2.Package(
            api_version = 2,
            project_id = 'foo',
            recipes_path = 'path/to/recipes',
          )
        )],
      be.updates(sha_a, sha_b, ['path1', 'path2']))
    self.assertMultiDone(requests_get)


  @mock.patch('requests.get')
  def test_commit_metadata(self, requests_get):
    requests_get.side_effect = multi(
      self.j('repo/+/revision?format=JSON', self.a_dat),
      self.j('repo/+/%s?format=JSON' % self.a, self.a_dat),
      self.d('repo/+/%s/infra/config/recipes.cfg?format=TEXT' % self.a,
             self.proto_text)
    )

    result = fetch.GitilesBackend('dir', 'repo', True).commit_metadata(
        'revision')
    self.assertEqual(result, self.a_meta)
    self.assertMultiDone(requests_get)

  @mock.patch('requests.get')
  def test_non_transient_error(self, requests_get):
    requests_get.side_effect = multi(
      self.r('repo/+/revision?format=JSON', fetch.GitilesFetchError(403, '')),
    )
    with self.assertRaises(fetch.GitilesFetchError):
      fetch.GitilesBackend('dir', 'repo', True).commit_metadata(
          'revision')
    self.assertMultiDone(requests_get)

  @mock.patch('requests.get')
  @mock.patch('time.sleep')
  @mock.patch('logging.exception')
  def test_transient_retry(self, _logging_exception, _time_sleep, requests_get):
    requests_get.side_effect = multi(
      self.r('repo/+/revision?format=JSON', fetch.GitilesFetchError(500, '')),
      self.r('repo/+/revision?format=JSON', fetch.GitilesFetchError(500, '')),
      self.r('repo/+/revision?format=JSON', fetch.GitilesFetchError(500, '')),
      self.r('repo/+/revision?format=JSON', fetch.GitilesFetchError(500, '')),
      self.j('repo/+/revision?format=JSON', self.a_dat),
      self.j('repo/+/%s?format=JSON' % self.a, self.a_dat),
      self.d('repo/+/%s/infra/config/recipes.cfg?format=TEXT' % self.a,
             self.proto_text),
    )

    result = fetch.GitilesBackend('dir', 'repo', True).commit_metadata(
        'revision')
    self.assertEqual(result, self.a_meta)
    self.assertMultiDone(requests_get)

if __name__ == '__main__':
  unittest.main()
