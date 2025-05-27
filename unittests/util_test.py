#!/usr/bin/env vpython3
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import copy

import test_env

from recipe_engine import util


class TestSentinel(test_env.RecipeEngineUnitTest):
  SENTINEL = util.sentinel('SENTINEL')

  def test_repr(self):
    self.assertEqual(repr(self.SENTINEL), 'SENTINEL')

  def test_copy(self):
    self.assertIs(copy.copy(self.SENTINEL), self.SENTINEL)

  def test_deepcopy(self):
    self.assertIs(copy.deepcopy(self.SENTINEL), self.SENTINEL)


if __name__ == '__main__':
  test_env.main()
