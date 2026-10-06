#!/usr/bin/env vpython3
# Copyright 2013 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os

import test_env

from recipe_engine.internal import engine_env


class TestMergeEnvs(test_env.RecipeEngineUnitTest):
  def setUp(self) -> None:
    super().setUp()
    self.original = {
        'FOO': 'foo',
    }

  @staticmethod
  def pathjoin(*parts: str) -> str:
    return os.pathsep.join(parts)

  def _merge(
      self,
      overrides: Mapping[str, str | None],
      prefixes: Mapping[str, Sequence[str]],
      suffixes: Mapping[str, Sequence[str]],
  ) -> dict[str, str]:
    return engine_env.merge_envs(
        self.original, overrides, prefixes, suffixes, os.pathsep)[0]

  def test_nothing_to_do(self) -> None:
    self.assertEqual(
        self._merge({}, {}, {}),
        self.original)

  def test_merge_with_empty_path_tuple(self) -> None:
    self.assertEqual(self._merge(
      {'FOO': ''}, {'FOO': ()}, {'FOO': ()}),
      {'FOO': ''})

  def test_merge_with_path_tuple(self) -> None:
    self.assertEqual(self._merge(
      {}, {'BAR': ('bar', 'baz')}, {'BAR': ('hat',)}),
      {'FOO': 'foo', 'BAR': self.pathjoin('bar', 'baz', 'hat')})

  def test_merge_with_path_tuple_and_orig_env(self) -> None:
    self.assertEqual(self._merge(
      {}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'foo', 'hat')})

  def test_merge_with_path_tuple_and_env(self) -> None:
    self.assertEqual(self._merge(
      {'FOO': 'override'}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'override', 'hat')})

  def test_merge_with_path_tuple_and_env_subst(self) -> None:
    self.assertEqual(self._merge(
      {'FOO': 'a-%(FOO)s-b'}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'a-foo-b', 'hat')})

  def test_merge_with_path_tuple_and_env_empty_subst(self) -> None:
    self.original['FOO'] = ''
    self.assertEqual(self._merge(
      {'FOO': '%(FOO)s'}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'hat')})

  def test_merge_with_path_tuple_and_env_clear(self) -> None:
    self.assertEqual(self._merge(
      {'FOO': None}, {'FOO': ('bar', 'baz')}, {'FOO': ('hat',)}),
      {'FOO': self.pathjoin('bar', 'baz', 'hat')})

  def test_merge_with_subst(self) -> None:
    self.assertEqual(self._merge(
        {'FOO': 'a-%(FOO)s-b'}, {}, {}),
        {'FOO': 'a-foo-b'})

  def test_merge_with_empty_subst(self) -> None:
    self.original['FOO'] = ''
    self.assertEqual(self._merge(
        {'FOO': '%(FOO)s'}, {}, {}),
        {'FOO': ''})

  def test_merge_with_clear(self) -> None:
    self.assertEqual(self._merge(
        {'FOO': None}, {}, {}),
        {})


if __name__ == '__main__':
  test_env.main()
