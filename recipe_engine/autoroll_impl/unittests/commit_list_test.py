#!/usr/bin/env vpython
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys
import unittest

import test_env

from recipe_engine.autoroll_impl.commit_list import CommitList


class TestCommitList(test_env.BaseCommitTest):
  def test_empty(self):
    with self.assertRaisesRegexp(AssertionError, 'is empty'):
      CommitList([])

  def test_single(self):
    c = self.cm()
    cl = CommitList([c])
    self.assertEqual(len(cl), 1)
    self.assertEqual(cl.current, c)
    self.assertEqual(cl.next, None)
    self.assertEqual(cl.next_roll_candidate, (None, None))

    self.assertEqual(cl.advance(), None)
    self.assertEqual(cl.current, c)

  def test_five(self):
    cs = [self.cm() for _ in xrange(5)]
    cl = CommitList(cs)
    self.assertEqual(len(cl), 5)

    self.assertEqual(cl.current, cs[0])
    self.assertEqual(cl.next, cs[1])

    cl.advance()
    self.assertEqual(cl.current, cs[1])
    self.assertEqual(cl.next, cs[2])

    self.assertEqual(cl.lookup(cs[0].revision), cs[0])

    self.assertEqual(cl.dist_to(cs[0].revision), -1)
    self.assertEqual(cl.dist_to(cs[1].revision), 0)
    self.assertEqual(cl.dist_to(cs[4].revision), 3)
    self.assertEqual(cl.dist_to('not_a_known_commit'), 4)

    self.assertEqual(cl.advance_to('not_a_known_commit'), None)
    self.assertEqual(cl.current, cs[1])

    self.assertEqual(cl.advance_to(cs[4].revision), cs[4])
    self.assertEqual(cl.current, cs[4])

  def test_deps(self):
    cs1 = [self.cm('1') for _ in xrange(5)]
    cs2 = [
      self.cm('2', [cs1[3]]),  # simulates an out-of-order dependency (revert)
      self.cm('2', [cs1[0]]),
      self.cm('2', [cs1[0]]),
      self.cm('2', [cs1[1]]),
      self.cm('2', [cs1[3]]),
      self.cm('2', [cs1[3]]),
    ]

    cl1 = CommitList(cs1)
    self.assertEqual(cl1.dist_compatible_with('2', cs2[0].revision), 0)

    cl2 = CommitList(cs2)

    # current one is compatible, so distance is 0
    self.assertEqual(cl2.dist_compatible_with('1', cs1[3].revision), 0)

    cl2.advance()
    # now the version is cs1[0], so the distance is 3
    self.assertEqual(cl2.dist_compatible_with('1', cs1[3].revision), 3)
    self.assertEqual(cl2.dist_compatible_with('1', 'not_a_known_commit'), 5)

    cl2.advance()
    # and now it's 2
    self.assertEqual(cl2.dist_compatible_with('1', cs1[3].revision), 2)


if __name__ == '__main__':
  sys.exit(unittest.main())
