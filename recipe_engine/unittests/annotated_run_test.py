#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import inspect
import unittest

import test_env  # pylint: disable=W0403,W0611

from slave import annotated_run


def S(name, *args):
  """Convenience method for a step dict."""
  if args:
    return {'name': name, 'seed_steps': list(args)}
  else:
    return {'name': name}


def G(*args):
  """Convenience method for a generator"""
  for a in args:
    yield a


class AnnotatedRunTest(unittest.TestCase):
  def testEnsureSequenceOfSteps(self):
    E = annotated_run.EXECUTE_NOW_SENTINEL
    for (inp, exp) in [
        ([S(1)],
         [S(1)]),
        ([S(1), S(2)],
         [S(1), S(2)]),
        ([S(1), [S(2), S(3)]],
         [S(1), S(2), S(3)]),
        ([[S(1), S(2)], S(3)],
         [S(1), S(2), S(3)]),
        (G(S(1)),
         [S(1), E]),
        (G(S(1), S(2)),
         [S(1), E, S(2), E])]:
      self.assertEquals(exp, list(annotated_run.ensure_sequence_of_steps(inp)))

  def testFixupSeedSteps(self):
    for (inp, exp) in [
        ([S(1)],
         [S(1)]),
        ([S(1), S(2)],
         [S(1, 1, 2), S(2)]),
        ([S(1), [S(2), S(3)]],
         [S(1, 1, 2, 3), S(2), S(3)]),
        ([[S(1), S(2)], S(3)],
         [S(1, 1, 2, 3), S(2), S(3)]),
        (G(S(1)),
         [S(1)]),
        (G(S(1), S(2)),
         [S(1), S(2)]),
        ([S(1), G(S(2), S(3))],
         [S(1, 1, 2), S(2), S(3)]),
        ([G(S(1), S(2)), S(3)],
         [S(1), S(2), S(3)]),
        (G(S(1), G(S(2), S(3))),
         [S(1), S(2), S(3)]),
        (G(G(S(1), S(2)), S(3)),
         [S(1), S(2), S(3)]),
        (G(S(1), [S(2), S(3)]),
         [S(1), S(2, 2, 3), S(3)]),
        (G([S(1), S(2)], S(3)),
         [S(1, 1, 2), S(2), S(3)]),
        (G([G(S(1)), S(2)], [S(3)], [G(S(4), S(5)), S(6)]),
         [S(1), S(2), S(3), S(4), S(5), S(6)])]:
      self.assertEquals(exp, list(annotated_run.fixup_seed_steps(inp)))

  def testFixupSeedStepsInvariant(self):
    """Invariant: After any inner generator yields, it must hold that the
    outermost generator consumer consumes this step before the inner generator
    yields the next time.
    """
    class InnerGenerator():
      """A generator that verifies through a callback that any element it
      yields is consumed by the outermost consumer."""

      def __init__(self, test, cb):
        self.cb = cb
        self.test = test
        self.got_it = False

      def GotIt(self):
        self.got_it = True

      def G(self, *args):
        for a in args:
          self.got_it = False
          if isinstance(a, dict):
            self.cb(a['name'], self.GotIt)
          if isinstance(a, list) and isinstance(a[-1], dict):
            # TODO(machenbach): This only tests one level of nesting.
            self.cb(a[-1]['name'], self.GotIt)
          if inspect.isgenerator(a):
            # If it is a generator then this generator will make sure the
            # invariant holds.
            self.got_it = True
          yield a
          self.test.assertTrue(self.got_it)


    class OuterConsumer():
      """A generator consumer that provides a callback to inner generators. It
      will add hooks for each item yielded by an inner generator and call them
      when the item was consumed."""

      def __init__(self):
        self.cbs = {}

      def cb(self, item, got_it):
        self.cbs.setdefault(item, []).append(got_it)

      def consume(self, gen):
        for a in gen:
          for c in self.cbs.setdefault(a['name'], []):
            c()
          del self.cbs[a['name']]

    T = annotated_run.fixup_seed_steps
    c = OuterConsumer()
    I = InnerGenerator(self, c.cb).G
    C = c.consume
    C(T(I(S(1), S(2))))

    c = OuterConsumer()
    I = InnerGenerator(self, c.cb).G
    C = c.consume
    C(T(I([I(S(1)), S(2)], [S(3)], [I(S(4), S(5)), S(6)])))


if __name__ == '__main__':
  unittest.main()
