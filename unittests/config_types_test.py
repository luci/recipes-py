#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import unittest

import test_env

from recipe_engine import config_types


class TestPathsPreGlobalInit(unittest.TestCase):
  """Test case for config_types.Path prior to recipe_engine/path module
  initialization.
  """

  def tearDown(self) -> None:
    config_types.CheckoutBasePath._resolved = None
    return super().tearDown()

  def test_path_construction_resolved(self) -> None:
    # Doesn't raise any errors
    cachePath = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))
    assert isinstance(cachePath.base, config_types.ResolvedBasePath)
    self.assertEqual(cachePath.base.resolved, '[CACHE]')
    self.assertEqual(cachePath.pieces, ())

  def test_path_construction_checkout(self) -> None:
    checkoutPath = config_types.Path(config_types.CheckoutBasePath())
    assert isinstance(checkoutPath.base, config_types.CheckoutBasePath)

  def test_path_construction_error_base(self) -> None:
    with self.assertRaisesRegex(ValueError, 'First argument'):
      config_types.Path('yo')  # type: ignore

  def test_path_construction_error_pieces(self) -> None:
    with self.assertRaisesRegex(ValueError, 'must only be `str`'):
      config_types.Path(
          config_types.ResolvedBasePath('[CACHE]'), 100  # type: ignore
      )

  def test_path_construction_error_backslash(self) -> None:
    with self.assertRaisesRegex(ValueError, 'contain backslash'):
      config_types.Path(config_types.ResolvedBasePath('[CACHE]'), 'bad\\path')

  def test_path_construction_resolved_pieces(self) -> None:
    a = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'), 'hello', 'world'
    )
    self.assertEqual(a.pieces, ('hello', 'world'))

    b = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'), 'hello/world'
    )
    self.assertEqual(b.pieces, ('hello', 'world'))

    self.assertEqual(a, b)

  def test_path_construction_checkout_pieces(self) -> None:
    a = config_types.Path(config_types.CheckoutBasePath(), 'hello', 'world')
    self.assertEqual(a.pieces, ('hello', 'world'))

    b = config_types.Path(config_types.CheckoutBasePath(), 'hello/world')
    self.assertEqual(b.pieces, ('hello', 'world'))

    # Note that these can be compared when they are both based on
    # CheckoutBasePath.
    self.assertEqual(a, b)

  def test_path_equality_non_path_type(self) -> None:
    a = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'), 'hello', 'world'
    )
    self.assertNotEqual(a, None)

  def test_path_inequality_resolved(self) -> None:
    p = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))
    self.assertLess(p / 'a', p / 'b')
    self.assertLess(p / 'a', p / 'b' / 'c')
    self.assertLess(p / 'a' / 'c', p / 'b' / 'c')

  def test_path_inequality_checkout(self) -> None:
    p = config_types.Path(config_types.CheckoutBasePath())
    self.assertLess(p / 'a', p / 'b')
    self.assertLess(p / 'a', p / 'b' / 'c')
    self.assertLess(p / 'a' / 'c', p / 'b' / 'c')

  def test_path_inequality_non_path_type(self) -> None:
    a = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'), 'hello', 'world'
    )
    with self.assertRaisesRegex(TypeError, "'<' not supported"):
      a < None  # type: ignore[operator]

  def test_path_inequality_mismatch(self) -> None:
    a = config_types.Path(config_types.CheckoutBasePath())
    b = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))
    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      self.assertLess(a, b)

  def test_path_equality_mismatch(self) -> None:
    a = config_types.Path(config_types.CheckoutBasePath())
    b = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))
    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      self.assertEqual(a, b)

  def test_path_dots_removal(self) -> None:
    p = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))

    self.assertEqual(p / 'hello', p / '.' / 'hello' / '.' / '.')

    self.assertEqual(p, p / '.')

    self.assertEqual(
        p / 'some/hello',
        # Note that no one would ever construct a path with all these styles,
        # however it's important that all the various joinery/embedded slash
        # styles result in the same Path because recipe code passes Paths around
        # and joins to them in multiple methods, so while we would never see
        # such a construction all in one line like this, it's possible that
        # a Path is logically constructed in multiple places in this fashion.
        (p / 'some/path/to/stuff' / '../..').joinpath('etc', '..////.', '..',
                                                      'hello'))

  def test_path_dots_removal_error(self) -> None:
    p = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))

    with self.assertRaisesRegex(ValueError, 'going above the base'):
      print(repr(p / '..'))

    with self.assertRaisesRegex(ValueError, 'going above the base'):
      print(repr(p / 'something' / '..///./..'))

  def test_path_joinpath(self) -> None:
    """Tests for Path.joinpath()."""
    base_path = config_types.Path(config_types.ResolvedBasePath('[START_DIR]'))
    reference_path = base_path.joinpath('foo').joinpath('bar')
    self.assertEqual(base_path / 'foo' / 'bar', reference_path)

  def test_path_joinpath_with_path(self) -> None:
    start_path = config_types.Path(config_types.ResolvedBasePath('[START_DIR]'))
    cache_path = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))
    self.assertEqual(
        start_path.joinpath('foo', cache_path, 'bar'), cache_path / 'bar'
    )

  def test_path_joinpath_with_none(self) -> None:
    base_path = config_types.Path(config_types.ResolvedBasePath('[START_DIR]'))
    with self.assertRaisesRegex(
        ValueError, 'Variadic arguments to Path must only be `str`'):
      base_path.joinpath(None)  # type: ignore[arg-type]

  def test_is_parent_of(self) -> None:
    p = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))

    self.assertTrue(p in (p / 'a').parents)
    self.assertTrue(p in (p / 'a' / 'b' / 'c').parents)
    self.assertTrue(p / 'a' in (p / 'a' / 'b' / 'c').parents)

  def test_is_parent_of_mismatch(self) -> None:
    p1 = config_types.Path(config_types.ResolvedBasePath('[CACHE]'))
    p2 = config_types.Path(config_types.ResolvedBasePath('[CLEANUP]'))

    self.assertFalse(p1 in p2.parents)
    self.assertFalse(p2 in p1.parents)

  def test_is_parent_of_checkout(self) -> None:
    p1 = config_types.Path(config_types.CheckoutBasePath(), 'some')
    p2 = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'),
        'builder',
        'src',
        'some',
        'thing',
    )

    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      p1 in p2.parents
    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      p2 in p1.parents

    config_types.CheckoutBasePath._resolved = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'), 'builder', 'src'
    )

    self.assertTrue(p1 in p2.parents)
    self.assertFalse(p2 in p1.parents)

  def test_is_parent_of_checkout_mismatch(self) -> None:
    p1 = config_types.Path(config_types.CheckoutBasePath(), 'some')
    p2 = config_types.Path(
        config_types.ResolvedBasePath('[CLEANUP]'), 'unrelated'
    )

    config_types.CheckoutBasePath._resolved = config_types.Path(
        config_types.ResolvedBasePath('[CACHE]'), 'builder', 'src'
    )

    self.assertFalse(p1 in p2.parents)
    self.assertFalse(p2 in p1.parents)

  def test_is_parent_of_check(self) -> None:
    p = config_types.Path(config_types.ResolvedBasePath('[CLEANUP]'))
    self.assertFalse(p / 'a' in (p / 'ab').parents)
    self.assertFalse(p / 'ab' in (p / 'a').parents)

  def test_relative_to_parent(self) -> None:
    p1 = config_types.Path(
        config_types.ResolvedBasePath('[CLEANUP]'), 'foo', 'bar', 'baz'
    )
    p2 = config_types.Path(config_types.ResolvedBasePath('[CLEANUP]'), 'foo')
    self.assertEqual(p1.relative_to(p2), 'bar/baz')
    with self.assertRaises(config_types.RelativeToNotParent):
      p2.relative_to(p1)

  def test_relative_to_different_base(self) -> None:
    p1 = config_types.Path(config_types.ResolvedBasePath('[CLEANUP]'), 'foo')
    p2 = config_types.Path(config_types.ResolvedBasePath('[CACHE]'), 'bar')
    with self.assertRaises(config_types.RelativeToDifferentBases):
      p1.relative_to(p2)
    with self.assertRaises(config_types.RelativeToDifferentBases):
      p2.relative_to(p1)

  def test_relative_to_walk_up_parent(self) -> None:
    p1 = config_types.Path(
        config_types.ResolvedBasePath('[CLEANUP]'), 'foo', 'bar', 'baz'
    )
    p2 = config_types.Path(config_types.ResolvedBasePath('[CLEANUP]'), 'foo')
    self.assertEqual(p1.relative_to(p2, walk_up=True), 'bar/baz')
    self.assertEqual(p2.relative_to(p1, walk_up=True), '../..')

  def test_relative_to_walk_up_sibling(self) -> None:
    p1 = config_types.Path(
        config_types.ResolvedBasePath('[CLEANUP]'), 'foo', 'bar'
    )
    p2 = config_types.Path(
        config_types.ResolvedBasePath('[CLEANUP]'), 'foo', 'baz'
    )
    self.assertEqual(p1.relative_to(p2, walk_up=True), '../bar')
    self.assertEqual(p2.relative_to(p1, walk_up=True), '../baz')


class TestPathsPostGlobalInit(unittest.TestCase):
  """Test case for config_types.Path."""

  def tearDown(self) -> None:
    config_types.ResetGlobalVariableAssignments()
    return super().tearDown()


if __name__ == '__main__':
  test_env.main()
