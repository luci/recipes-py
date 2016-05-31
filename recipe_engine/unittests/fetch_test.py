#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
THIRD_PARTY = os.path.join(BASE_DIR, 'recipe_engine', 'third_party')
sys.path.insert(0, os.path.join(THIRD_PARTY, 'mock-1.0.1'))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, THIRD_PARTY)

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
    fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=True)
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
    fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=True)
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
      fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=False)

  @mock.patch('os.path.isdir')
  @mock.patch('recipe_engine.fetch._run_git')
  def test_unclean_filesystem(self, run_git, isdir):
    isdir.side_effect = [True, False]
    with self.assertRaises(fetch.UncleanFilesystemError):
      fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=False)
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
      fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=False)
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
    fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=True)
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
      fetch.ensure_git_checkout('repo', 'revision', 'dir', allow_fetch=False)
    isdir.assert_has_calls([
      mock.call('dir'),
      mock.call('dir/.git'),
    ])
    run_git.assert_has_calls([
      mock.call('dir', 'config', 'remote.origin.url'),
      mock.call('dir', 'rev-parse', '-q', '--verify', 'revision^{commit}'),
    ])


if __name__ == '__main__':
  unittest.main()
