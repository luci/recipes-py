#!/usr/bin/env vpython3
# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import unittest

import test_env  # for sys.path manipulation

from recipe_engine.config_types import Path, ResolvedBasePath, CheckoutBasePath
from recipe_engine.config_types import ResetGlobalVariableAssignments


class TestPathsPreGlobalInit(unittest.TestCase):
  """Test case for config_types.Path prior to recipe_engine/path module
  initialization.
  """

  def tearDown(self) -> None:
    CheckoutBasePath._resolved = None
    return super().tearDown()

  def test_path_construction_resolved(self):
    # Doesn't raise any errors
    cachePath = Path(ResolvedBasePath('[CACHE]'))
    assert isinstance(cachePath.base, ResolvedBasePath)
    self.assertEqual(cachePath.base.resolved, '[CACHE]')
    self.assertEqual(cachePath.pieces, ())

  def test_path_construction_checkout(self):
    checkoutPath = Path(CheckoutBasePath())
    assert isinstance(checkoutPath.base, CheckoutBasePath)

  def test_path_construction_error_base(self):
    with self.assertRaisesRegex(ValueError, 'First argument'):
      Path('yo')  # type: ignore

  def test_path_construction_error_pieces(self):
    with self.assertRaisesRegex(ValueError, 'must only be `str`'):
      Path(ResolvedBasePath('[CACHE]'), 100)  # type: ignore

  def test_path_construction_error_backslash(self):
    with self.assertRaisesRegex(ValueError, 'contain backslash'):
      Path(ResolvedBasePath('[CACHE]'), 'bad\\path')

  def test_path_construction_resolved_pieces(self):
    a = Path(ResolvedBasePath('[CACHE]'), 'hello', 'world')
    self.assertEqual(a.pieces, ('hello', 'world'))

    b = Path(ResolvedBasePath('[CACHE]'), 'hello/world')
    self.assertEqual(b.pieces, ('hello', 'world'))

    self.assertEqual(a, b)

  def test_path_construction_checkout_pieces(self):
    a = Path(CheckoutBasePath(), 'hello', 'world')
    self.assertEqual(a.pieces, ('hello', 'world'))

    b = Path(CheckoutBasePath(), 'hello/world')
    self.assertEqual(b.pieces, ('hello', 'world'))

    # Note that these can be compared when they are both based on
    # CheckoutBasePath.
    self.assertEqual(a, b)

  def test_path_equality_non_path_type(self):
    a = Path(ResolvedBasePath('[CACHE]'), 'hello', 'world')
    self.assertNotEqual(a, None)

  def test_path_inequality_resolved(self):
    p = Path(ResolvedBasePath('[CACHE]'))
    self.assertLess(p / 'a', p / 'b')
    self.assertLess(p / 'a', p / 'b' / 'c')
    self.assertLess(p / 'a' / 'c', p / 'b' / 'c')

  def test_path_inequality_checkout(self):
    p = Path(CheckoutBasePath())
    self.assertLess(p / 'a', p / 'b')
    self.assertLess(p / 'a', p / 'b' / 'c')
    self.assertLess(p / 'a' / 'c', p / 'b' / 'c')

  def test_path_inequality_non_path_type(self):
    a = Path(ResolvedBasePath('[CACHE]'), 'hello', 'world')
    with self.assertRaisesRegex(TypeError, "'<' not supported"):
      a < None

  def test_path_inequality_mismatch(self):
    a = Path(CheckoutBasePath())
    b = Path(ResolvedBasePath('[CACHE]'))
    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      self.assertLess(a, b)

  def test_path_equality_mismatch(self):
    a = Path(CheckoutBasePath())
    b = Path(ResolvedBasePath('[CACHE]'))
    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      self.assertEqual(a, b)

  def test_path_dots_removal(self):
    p = Path(ResolvedBasePath('[CACHE]'))

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

  def test_path_dots_removal_error(self):
    p = Path(ResolvedBasePath('[CACHE]'))

    with self.assertRaisesRegex(ValueError, 'going above the base'):
      print(repr(p / '..'))

    with self.assertRaisesRegex(ValueError, 'going above the base'):
      print(repr(p / 'something' / '..///./..'))

  def test_path_joinpath(self):
    """Tests for Path.joinpath()."""
    base_path = Path(ResolvedBasePath('[START_DIR]'))
    reference_path = base_path.joinpath('foo').joinpath('bar')
    self.assertEqual(base_path / 'foo' / 'bar', reference_path)

  def test_path_joinpath_with_path(self):
    start_path = Path(ResolvedBasePath('[START_DIR]'))
    cache_path = Path(ResolvedBasePath('[CACHE]'))
    self.assertEqual(start_path.joinpath('foo', cache_path, 'bar'), cache_path / 'bar')

  def test_is_parent_of(self):
    p = Path(ResolvedBasePath('[CACHE]'))

    self.assertTrue(p in (p / 'a').parents)
    self.assertTrue(p in (p / 'a' / 'b' / 'c').parents)
    self.assertTrue(p / 'a' in (p / 'a' / 'b' / 'c').parents)

  def test_is_parent_of_mismatch(self):
    p1 = Path(ResolvedBasePath('[CACHE]'))
    p2 = Path(ResolvedBasePath('[CLEANUP]'))

    self.assertFalse(p1 in p2.parents)
    self.assertFalse(p2 in p1.parents)

  def test_is_parent_of_checkout(self):
    p1 = Path(CheckoutBasePath(), 'some')
    p2 = Path(ResolvedBasePath('[CACHE]'), 'builder', 'src', 'some', 'thing')

    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      p1 in p2.parents
    with self.assertRaisesRegex(ValueError, 'before checkout_dir is set'):
      p2 in p1.parents

    CheckoutBasePath._resolved = Path(
        ResolvedBasePath('[CACHE]'), 'builder', 'src')

    self.assertTrue(p1 in p2.parents)
    self.assertFalse(p2 in p1.parents)

  def test_is_parent_of_checkout_mismatch(self):
    p1 = Path(CheckoutBasePath(), 'some')
    p2 = Path(ResolvedBasePath('[CLEANUP]'), 'unrelated')

    CheckoutBasePath._resolved = Path(
        ResolvedBasePath('[CACHE]'), 'builder', 'src')

    self.assertFalse(p1 in p2.parents)
    self.assertFalse(p2 in p1.parents)

  def test_is_parent_of_check(self):
    p = Path(ResolvedBasePath('[CLEANUP]'))
    self.assertFalse(p / 'a' in (p / 'ab').parents)
    self.assertFalse(p / 'ab' in (p / 'a').parents)


class TestPathsPostGlobalInit(unittest.TestCase):
  """Test case for config_types.Path."""

  def tearDown(self):
    ResetGlobalVariableAssignments()
    return super().tearDown()


if __name__ == '__main__':
  test_env.main()
