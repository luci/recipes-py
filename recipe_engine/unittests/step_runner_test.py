#!/usr/bin/env python
# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import unittest

import test_env

from recipe_engine import step_runner


class TestLinebuf(unittest.TestCase):
  def test_add_partial(self):
    lb = step_runner._streamingLinebuf()
    lb.ingest("blarf")
    self.assertEqual([], lb.get_buffered())

    self.assertEqual([], lb.buffedlines)
    self.assertEqual("blarf", lb.extra.getvalue())

  def test_add_whole(self):
    lb = step_runner._streamingLinebuf()
    lb.ingest("blarf\n")
    self.assertEqual(["blarf"], lb.get_buffered())

    self.assertEqual([], lb.buffedlines)
    self.assertEqual("", lb.extra.getvalue())

  def test_add_partial_whole(self):
    lb = step_runner._streamingLinebuf()
    lb.ingest("foof\nfleem\nblarf")
    self.assertEqual(["foof", "fleem"], lb.get_buffered())

    lb.ingest("dweeble\nwat")
    self.assertEqual(["blarfdweeble"], lb.get_buffered())

    self.assertEqual([], lb.buffedlines)
    self.assertEqual("wat", lb.extra.getvalue())

  def test_leftovers(self):
    lb = step_runner._streamingLinebuf()

    lb.ingest("nerds")
    self.assertEqual([], lb.get_buffered())

    lb.ingest("doop\n")
    self.assertEqual(["nerdsdoop"], lb.get_buffered())

    self.assertEqual([], lb.get_buffered())

    self.assertEqual([], lb.buffedlines)
    self.assertEqual("", lb.extra.getvalue())


if __name__ == '__main__':
  unittest.main()
