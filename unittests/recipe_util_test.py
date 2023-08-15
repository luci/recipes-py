# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import unittest

import test_env

from recipe_engine import recipe_utils


class TestUtils(test_env.RecipeEngineUnitTest):

  def test_check_type_good(self):
    recipe_utils.check_type("4", 4, int)

  def test_check_type_bad(self):
    with self.assertRaises(TypeError):
      recipe_utils.check_type("4", 4, str)

  def test_check_list_type_good(self):
    recipe_utils.check_list_type("[4]", [4], int)

  def test_check_list_type_bad(self):
    with self.assertRaises(TypeError):
      recipe_utils.check_list_type("[4]", [4], str)

  def test_check_dict_type_good(self):
    recipe_utils.check_dict_type("{4: 4}", {4: 4}, int, int)

  def test_check_dict_type_bad(self):
    with self.assertRaises(TypeError):
      recipe_utils.check_dict_type("{4: 4}", {4: 4}, str, int)


if __name__ == "__main__":
  test_env.main()
