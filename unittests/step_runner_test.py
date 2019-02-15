#!/usr/bin/env vpython
# Copyright 2013 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os

import test_env

from recipe_engine import step_runner


class TestLinebuf(test_env.RecipeEngineUnitTest):
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


class TestMergeEnvs(test_env.RecipeEngineUnitTest):
  def setUp(self):
    super(TestMergeEnvs, self).setUp()
    self.original = {
        'FOO': 'foo',
    }

  @staticmethod
  def pathjoin(*parts):
    return os.pathsep.join(parts)

  def _merge(self, overrides, prefixes, suffixes):
    return step_runner._merge_envs(self.original, overrides, prefixes, suffixes,
                                   os.pathsep)

  def test_nothing_to_do(self):
    self.assertEqual(
        self._merge({}, {}, {}),
        self.original)

  def test_merge_with_empty_path_tuple(self):
    self.assertEqual(self._merge(
      {'FOO': ''}, {'FOO': ()}, {'FOO': ()}),
      {'FOO': ''})

  def test_merge_with_path_tuple(self):
    self.assertEqual(self._merge(
      {}, {'BAR': ('bar', 'baz')}, {'BAR': ('hat',)}),
      {'FOO': 'foo', 'BAR': self.pathjoin('bar', 'baz', 'hat')})

  def test_merge_with_path_tuple_and_orig_env(self):
    self.assertEqual(self._merge(
      {}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'foo', 'hat')})

  def test_merge_with_path_tuple_and_env(self):
    self.assertEqual(self._merge(
      {'FOO': 'override'}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'override', 'hat')})

  def test_merge_with_path_tuple_and_env_subst(self):
    self.assertEqual(self._merge(
      {'FOO': 'a-%(FOO)s-b'}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'a-foo-b', 'hat')})

  def test_merge_with_path_tuple_and_env_empty_subst(self):
    self.original['FOO'] = ''
    self.assertEqual(self._merge(
      {'FOO': '%(FOO)s'}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'hat')})

  def test_merge_with_path_tuple_and_env_clear(self):
    self.assertEqual(self._merge(
      {'FOO': None}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'hat')})

  def test_merge_with_subst(self):
    self.assertEqual(self._merge(
        {'FOO': 'a-%(FOO)s-b'}, {}, {}),
        {'FOO': 'a-foo-b'})

  def test_merge_with_empty_subst(self):
    self.original['FOO'] = ''
    self.assertEqual(self._merge(
        {'FOO': '%(FOO)s'}, {}, {}),
        {'FOO': ''})

  def test_merge_with_clear(self):
    self.assertEqual(self._merge(
        {'FOO': None}, {}, {}),
        {})


if __name__ == '__main__':
  test_env.main()
