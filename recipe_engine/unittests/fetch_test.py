#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import base64
import io
import json
import os
import sys
import unittest

import test_env

import mock
import subprocess42

from recipe_engine import fetch


class TestGit(unittest.TestCase):
  @mock.patch('recipe_engine.fetch._run_git')
  def test_fresh_clone(self, run_git):
    run_git.side_effect = [
      None,
      'repo\n',
      None,
      None,
    ]
    fetch.GitBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)
    run_git.assert_has_calls([
      mock.call(None, 'clone', '-q', 'repo', 'dir'),
      mock.call('dir', 'config', 'remote.origin.url'),
      mock.call('dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'),
      mock.call('dir', 'reset', '-q', '--hard', 'revision'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch._run_git')
  def test_existing_checkout(self, run_git, isdir):
    run_git.side_effect = [
      'repo\n',
      None,
      None,
    ]
    isdir.return_value = True
    fetch.GitBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    run_git.assert_has_calls([
      mock.call('dir', 'config', 'remote.origin.url'),
      mock.call('dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'),
      mock.call('dir', 'reset', '-q', '--hard', 'revision'),
    ])

  @mock.patch('recipe_engine.fetch._run_git')
  def test_clone_not_allowed(self, run_git):
    with self.assertRaises(fetch.FetchNotAllowedError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch._run_git')
  def test_unclean_filesystem(self, run_git, isdir):
    isdir.side_effect = [True, False]
    with self.assertRaises(fetch.UncleanFilesystemError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch._run_git')
  def test_origin_mismatch(self, run_git, isdir):
    run_git.return_value = 'not-repo'
    isdir.return_value = True
    with self.assertRaises(fetch.UncleanFilesystemError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    run_git.assert_has_calls([
      mock.call('dir', 'config', 'remote.origin.url'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch._run_git')
  def test_rev_parse_fail(self, run_git, isdir):
    run_git.side_effect = [
      'repo',
      subprocess42.CalledProcessError(1, ['fakecmd']),
      None,
      None,
    ]
    isdir.return_value = True
    fetch.GitBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    run_git.assert_has_calls([
      mock.call('dir', 'config', 'remote.origin.url'),
      mock.call('dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'),
      mock.call('dir', 'fetch'),
      mock.call('dir', 'reset', '-q', '--hard', 'revision'),
    ])

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch._run_git')
  def test_rev_parse_fetch_not_allowed(self, run_git, isdir):
    run_git.side_effect = [
      'repo',
      subprocess42.CalledProcessError(1, ['fakecmd']),
    ]
    isdir.return_value = True
    with self.assertRaises(fetch.FetchNotAllowedError):
      fetch.GitBackend().checkout(
          'repo', 'revision', 'dir', allow_fetch=False)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    run_git.assert_has_calls([
      mock.call('dir', 'config', 'remote.origin.url'),
      mock.call('dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'),
    ])


class TestGitiles(unittest.TestCase):
  @mock.patch('__builtin__.open', mock.mock_open())
  @mock.patch('shutil.rmtree')
  @mock.patch('os.makedirs')
  @mock.patch('tarfile.open')
  @mock.patch('requests.get')
  def test_checkout(self, requests_get, tarfile_open, makedirs, rmtree):
    proto_text = u"""
api_version: 1
project_id: "foo"
recipes_path: "path/to/recipes"
""".lstrip()
    requests_get.side_effect = [
        mock.Mock(text=u')]}\'\n{ "commit": "abc123" }'),
        mock.Mock(text=base64.b64encode(proto_text)),
        mock.Mock(content=''),
    ]

    fetch.GitilesBackend().checkout(
        'repo', 'revision', 'dir', allow_fetch=True)

    requests_get.assert_has_calls([
        mock.call('repo/+/revision?format=JSON'),
        mock.call('repo/+/abc123/infra/config/recipes.cfg?format=TEXT'),
        mock.call('repo/+archive/abc123/path/to/recipes.tar.gz'),
    ])

    makedirs.assert_has_calls([
      mock.call('dir/infra/config'),
      mock.call('dir/path/to/recipes'),
    ])

    rmtree.assert_called_once_with('dir', ignore_errors=True)

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
    requests_get.side_effect = [
        mock.Mock(text=u')]}\'\n{ "commit": "sha_a" }'),
        mock.Mock(text=u')]}\'\n{ "commit": "sha_b" }'),
        mock.Mock(text=u')]}\'\n%s' % json.dumps(log_json)),
    ]

    self.assertEqual(
        ['ghi789', 'abc123'],
        fetch.GitilesBackend().updates(
            'repo', 'reva', 'dir', True, 'revb',
            ['path1', 'path2']))

    requests_get.assert_has_calls([
        mock.call('repo/+/reva?format=JSON'),
        mock.call('repo/+/revb?format=JSON'),
        mock.call('repo/+log/sha_a..sha_b?name-status=1&format=JSON'),
    ])


if __name__ == '__main__':
  unittest.main()
