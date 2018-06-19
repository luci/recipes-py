#!/usr/bin/env vpython
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import unittest

import test_env

from recipe_engine import util


class TestMultiException(unittest.TestCase):

  def testNoExceptionsRaisesNothing(self):
    mb = util.MultiException.Builder()
    with mb.catch():
      pass
    mb.raise_if_any()

    mexc = util.MultiException()
    self.assertEqual(str(mexc), 'MultiException(No exceptions)')

  def testExceptionsRaised(self):
    fail_exc = Exception('fail!')
    mb = util.MultiException.Builder()
    with mb.catch():
      raise fail_exc

    mexc = mb.get()
    self.assertEqual(len(mexc), 1)
    self.assertIs(mexc[0], fail_exc)
    self.assertEqual(str(mexc), 'MultiException(fail!)')

  def testMultipleExceptions(self):
    mb = util.MultiException.Builder()
    with mb.catch():
      raise KeyError('One')
    with mb.catch():
      raise ValueError('Two')

    mexc = mb.get()
    self.assertIsNotNone(mexc)
    self.assertEqual(len(mexc), 2)

    exceptions = list(mexc)
    self.assertIsInstance(exceptions[0], KeyError)
    self.assertIsInstance(exceptions[1], ValueError)
    self.assertEqual(str(mexc), "MultiException('One', and 1 more...)")

  def testTargetedException(self):
    mb = util.MultiException().Builder()
    def not_caught():
      with mb.catch(ValueError):
        raise KeyError('One')
    self.assertRaises(KeyError, not_caught)
    self.assertIsNone(mb.get())


class TestMapDeferExceptions(unittest.TestCase):

  def testNoExceptionsDoesNothing(self):
    v = []
    util.map_defer_exceptions(lambda e: v.append(e), [1, 2, 3])
    self.assertEqual(v, [1, 2, 3])

  def testCatchesExceptions(self):
    v = []
    def fn(e):
      if e == 0:
        raise ValueError('Zero')
      v.append(e)

    mexc = None
    try:
      util.map_defer_exceptions(fn, [0, 1, 0, 0, 2, 0, 3, 0])
    except util.MultiException as e:
      mexc = e

    self.assertEqual(v, [1, 2, 3])
    self.assertIsNotNone(mexc)
    self.assertEqual(len(mexc), 5)

  def testCatchesSpecificExceptions(self):
    def fn(e):
      raise ValueError('Zero')
    self.assertRaises(ValueError, util.map_defer_exceptions, fn, [1], KeyError)


if __name__ == '__main__':
  unittest.main()
