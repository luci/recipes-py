#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import test_env

from recipe_engine import config_types


class TestPaths(test_env.RecipeEngineUnitTest):
  """Test case for config_types.Path."""
  base_path = config_types.Path(config_types.NamedBasePath('base'))

  def test_path_join(self) -> None:
    """Tests for Path.join()."""
    reference_path = self.base_path.join('foo').join('bar')
    self.assertEqual(self.base_path / 'foo' / 'bar', reference_path)

  def test_equality_after_separate(self) -> None:
    """Test that separating paths makes equality work.

    Config types don't know what platform they're running on. Thus, Paths don't
    know what their separator character is. Until their pieces are explicitly
    separated, two Paths representing identical locations might present as
    unequal.
    """
    path_with_slashes = self.base_path.join('foo/bar')
    path_with_multiple_pieces = self.base_path.join('foo', 'bar')
    # This first assertion isn't desired behavior, but it demonstrates the
    # problem being solved.
    self.assertNotEqual(path_with_slashes, path_with_multiple_pieces)
    path_with_slashes.separate('/')
    self.assertEqual(path_with_slashes, path_with_multiple_pieces)

  def test_parenthood_after_separate(self) -> None:
    """Test that separating paths makes parenthood checks work.

    Config types don't know what platform they're running on. Thus, Paths don't
    know what their separator character is. Until their pieces are explicitly
    separated, one path might represent a parent of another, but is_parent_of
    might not agree.
    """
    my_file = self.base_path.join('foo/bar.txt')
    my_dir = self.base_path.join('foo')
    # This first assertion isn't desired behavior, but it demonstrates the
    # problem being solved.
    self.assertFalse(my_dir.is_parent_of(my_file))
    my_file.separate('/')
    self.assertTrue(my_dir.is_parent_of(my_file))


if __name__ == '__main__':
  test_env.main()
