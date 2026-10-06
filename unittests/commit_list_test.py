#!/usr/bin/env vpython3
# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import struct
import sys
from typing import Any

import test_env

from PB.recipe_engine import recipes_cfg as recipes_cfg_pb

from recipe_engine.internal import fetch
from recipe_engine.internal.autoroll_impl import commit_list


class BaseCommitTest(test_env.RecipeEngineUnitTest):
  def __init__(self, *args: Any, **kwargs: Any) -> None:
    super().__init__(*args, **kwargs)
    self.cm_counter = 0
    self.cm_timestamp = 0

  def setUp(self) -> None:
    super().setUp()
    self.cm_counter = 0
    self.cm_timestamp = 1501807893

  def cm(
      self,
      repo: str = 'repo',
      deps: Sequence[fetch.CommitMetadata] = (),
      revision: str | None = None,
      author_email: str = 'author@example.com',
      commit_timestamp: int | None = None,
      message_lines: Sequence[str] = ('message', 'lines'),
      roll_candidate: bool = False,
  ) -> fetch.CommitMetadata:
    spec = recipes_cfg_pb.RepoSpec(
      api_version=2,
      repo_name=repo,
      canonical_repo_url='https://git.example.com/%s.git' % repo,
    )
    for commit in deps:
      repo = commit.spec.repo_name
      spec.deps[repo].url = commit.spec.canonical_repo_url
      spec.deps[repo].revision = commit.revision

    if revision is None:
      revision = hashlib.sha1(struct.pack('!Q', self.cm_counter)).hexdigest()
      self.cm_counter += 1

    if commit_timestamp is None:
      # Increase the commit timestamp by a non-fixed, yet deterministic, amount
      # so that commit timestamps are monotonically increasing.
      commit_timestamp = self.cm_timestamp
      self.cm_timestamp += 60 * (int(revision[:2], 16)+1)

    return fetch.CommitMetadata(revision, author_email, commit_timestamp,
                                message_lines, spec, roll_candidate)

  def cl(self, count: int) -> commit_list.CommitList:
    return commit_list.CommitList(
        'fake-repo', 'fake-branch', [self.cm() for _ in range(count)])


class TestCommitList(BaseCommitTest):
  def test_empty(self) -> None:
    with self.assertRaisesRegex(AssertionError, 'is empty'):
      commit_list.CommitList('fake-repo', 'fake-branch', [])

  def test_single(self) -> None:
    c = self.cm()
    cl = commit_list.CommitList('fake-repo', 'fake-branch', [c])
    self.assertEqual(len(cl), 1)
    cursor = cl.cursor()
    self.assertEqual(cursor.current, c)
    self.assertEqual(cursor.next_roll_candidate, None)

  def test_five(self) -> None:
    cs = [self.cm() for _ in range(5)]
    cl = commit_list.CommitList('fake-repo', 'fake-branch', cs)
    self.assertEqual(len(cl), 5)

    cursor = cl.cursor()
    self.assertEqual(cursor.current, cs[0])

    cursor.advance_to(cs[1].revision)
    self.assertEqual(cursor.current, cs[1])

    self.assertEqual(cl.lookup(cs[0].revision), cs[0])

    with self.assertRaises(commit_list.UnknownCommit):
      cursor.advance_to('not_a_known_commit')
    self.assertEqual(cursor.current, cs[1])

    cursor.advance_to(cs[4].revision)
    self.assertEqual(cursor.current, cs[4])

    with self.assertRaises(commit_list.BackwardsRoll):
      cursor.advance_to(cs[3].revision)
    self.assertEqual(cursor.current, cs[4])

  def test_dist(self) -> None:
    cs = [self.cm() for _ in range(5)]
    cl = commit_list.CommitList('fake-repo', 'fake-branch', cs)

    # 1 revision
    self.assertEqual(cl.dist(cs[0].revision), 0)
    self.assertEqual(cl.dist(cs[4].revision), 4)
    self.assertIsNone(cl.dist('unknown-revision'))

    # 2 revisions
    self.assertEqual(cl.dist(cs[0].revision, cs[4].revision), 4)
    self.assertEqual(cl.dist(cs[1].revision, cs[3].revision), 2)
    self.assertIsNone(cl.dist(cs[4].revision, cs[0].revision))
    self.assertIsNone(cl.dist(cs[0].revision, 'unknown-revision'))
    with self.assertRaises(commit_list.UnknownCommit):
      cl.dist('unknown-revision', cs[4].revision)

  def test_compatibility(self) -> None:
    cs1 = [self.cm('1') for _ in range(5)]
    cs2 = [
        self.cm('2', [cs1[3]]),  # simulates an out-of-order dependency (revert)
        self.cm('2', [cs1[0]]),
        self.cm('2', [cs1[0]]),
        self.cm('2', [cs1[1]]),
        self.cm('2', [cs1[3]]),
        self.cm('2'),  # simulates a dep being removed
        self.cm('2', [cs1[3]]),  # simulates a dep being added
    ]
    cs3 = [self.cm('3') for _ in range(3)]

    cl1 = commit_list.CommitList('fake-repo-1', 'fake-branch', cs1)
    cl2 = commit_list.CommitList('fake-repo-2', 'fake-branch', cs2)
    cl3 = commit_list.CommitList('fake-repo-3', 'fake-branch', cs3)

    self.assertTrue(cl2.is_compatible(cs2[0].revision, {'1': cs1[3].revision}))
    self.assertFalse(cl2.is_compatible(cs2[0].revision, {'1': cs1[0].revision}))

    self.assertTrue(cl2.is_compatible(cs2[0].revision, {'3': cs3[0].revision}))
    self.assertTrue(cl3.is_compatible(cs3[0].revision, {'2': cs2[0].revision}))

    self.assertEqual(
        cl2.compatible_commits({
            '1': cs1[3].revision,
            '3': cs3[0].revision
        }), [cs2[0], cs2[4], cs2[5], cs2[6]])


if __name__ == '__main__':
  sys.exit(test_env.main())
