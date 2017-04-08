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
        mock.patch('logging.warning'),
        mock.patch('logging.exception'),
        mock.patch('recipe_engine.fetch.GitBackend.Git._resolve_git',
                   return_value='GIT'),
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

  @mock.patch('recipe_engine.fetch.GitBackend.Git._execute')
  def test_fresh_clone(self, git):
    git.side_effect = multi(
      self.g(['clone', '-q', 'repo', 'dir']),
      self.g(['-C', 'dir', 'config', 'remote.origin.url', 'repo']),
      self.g(['-C', 'dir', 'rev-parse', '-q', '--verify', 'revision^{commit}']),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'revision']),
    )

    fetch.GitBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)

    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend.Git._execute')
  def test_existing_checkout(self, git, isdir):
    isdir.return_value = True
    git.side_effect = multi(
      self.g(['-C', 'dir', 'config', 'remote.origin.url', 'repo']),
      self.g(['-C', 'dir', 'rev-parse', '-q', '--verify', 'revision^{commit}']),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'revision']),
    )

    fetch.GitBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)

    self.assertMultiDone(git)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])

  @mock.patch('recipe_engine.fetch.GitBackend.Git._execute')
  def test_clone_not_allowed(self, _git):
    with self.assertRaises(fetch.FetchNotAllowedError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)

  @mock.patch('os.path.isdir')
  def test_unclean_filesystem(self, isdir):
    isdir.side_effect = [True, False]
    with self.assertRaises(fetch.UncleanFilesystemError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend.Git._execute')
  def test_rev_parse_fail(self, git, isdir):
    git.side_effect = multi(
      self.g(['-C', 'dir', 'config', 'remote.origin.url', 'repo']),
      self.g(['-C', 'dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'],
             CPE(1, ['no such revision'])),
      self.g(['-C', 'dir', 'fetch']),
      self.g(['-C', 'dir', 'reset', '-q', '--hard', 'revision']),
    )
    isdir.return_value = True


    fetch.GitBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    self.assertMultiDone(git)

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch.GitBackend.Git._execute')
  def test_rev_parse_fetch_not_allowed(self, git, isdir):
    git.side_effect = multi(
      self.g(['-C', 'dir', 'config', 'remote.origin.url', 'repo']),
      self.g(['-C', 'dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'],
             CPE(1, ['no such revision'])),
    )
    isdir.return_value = True
    with self.assertRaises(fetch.FetchNotAllowedError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    self.assertMultiDone(git)

  @mock.patch('recipe_engine.fetch.GitBackend.Git._execute')
  def test_commit_metadata(self, git):
    git.side_effect = multi(
      self.g(['-C', 'dir', 'show', '-s', '--pretty=%aE', 'revision'],
             'foo@example.com'),
      self.g(['-C','dir', 'show', '-s', '--pretty=%B', 'revision'],
             'message'),
    )

    result = fetch.GitBackend().commit_metadata(
        'repo', 'revision', 'dir', allow_fetch=True)

    self.assertEqual(result, {
      'author': 'foo@example.com',
      'message': 'message',
    })
    self.assertMultiDone(git)


class TestGitiles(unittest.TestCase):
  def setUp(self):
    requests_ssl.disable_check()
    fetch.Backend._GIT_METADATA_CACHE = {}

    self.proto_text = u"""{
  "api_version": 2,
  "project_id": "foo",
  "recipes_path": "path/to/recipes"
}""".lstrip()

    self.a = 'a'*40
    self.a_dat = {
      'commit': self.a,
      'author': {'email': 'foo@example.com'},
      'message': 'message',
    }
    self.a_meta = {
      'author': 'foo@example.com',
      'message': 'message',
    }

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
      self.d('repo/+/%s/infra/config/recipes.cfg?format=TEXT' % self.a,
             self.proto_text),
      self.d('repo/+archive/%s/path/to/recipes.tar.gz' % self.a, ''),
    )

    fetch.GitilesBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)

    makedirs.assert_has_calls([
      mock.call('dir/infra/config'),
      mock.call('dir/path/to/recipes'),
    ])

    rmtree.assert_called_once_with('dir', ignore_errors=True)
    self.assertMultiDone(requests_get)

  @mock.patch('requests.get')
  def test_updates(self, requests_get):
    log_json = {
      'log': [
        {
          'commit': 'abc123',
          'tree_diff': [
            {
              'old_path': '/dev/null',
              'new_path': 'path1/foo',
            },
          ],
        },
        {
          'commit': 'def456',
          'tree_diff': [
            {
              'old_path': '/dev/null',
              'new_path': 'path8/foo',
            },
          ],
        },
        {
          'commit': 'ghi789',
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
    sha_a = 'a'*40
    sha_b = 'b'*40
    requests_get.side_effect = multi(
      self.j('repo/+/reva?format=JSON', {'commit': sha_a}),
      self.j('repo/+/revb?format=JSON', {'commit': sha_b}),
      self.j('repo/+log/%s..%s?name-status=1&format=JSON' % (sha_a, sha_b),
             log_json),
    )

    be = fetch.GitilesBackend()

    self.assertEqual(
        ['ghi789', 'abc123'],
        be.updates('repo', 'reva', 'dir', True, 'revb', ['path1', 'path2']))

    self.assertMultiDone(requests_get)


  @mock.patch('requests.get')
  def test_commit_metadata(self, requests_get):
    requests_get.side_effect = multi(
      self.j('repo/+/revision?format=JSON', self.a_dat),
    )

    result = fetch.GitilesBackend().commit_metadata(
        'repo', 'revision', 'dir', allow_fetch=True)
    self.assertEqual(result, self.a_meta)
    self.assertMultiDone(requests_get)

  @mock.patch('requests.get')
  def test_non_transient_error(self, requests_get):
    requests_get.side_effect = multi(
      self.r('repo/+/revision?format=JSON', fetch.GitilesFetchError(403, '')),
    )
    with self.assertRaises(fetch.GitilesFetchError):
      fetch.GitilesBackend().commit_metadata(
          'repo', 'revision', 'dir', allow_fetch=True)
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
    )

    result = fetch.GitilesBackend().commit_metadata(
        'repo', 'revision', 'dir', allow_fetch=True)
    self.assertEqual(result, self.a_meta)
    self.assertMultiDone(requests_get)

if __name__ == '__main__':
  unittest.main()
