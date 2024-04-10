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
        (p / 'some/path/to/stuff' / '../..').join('etc', '..////.', '..',
                                                  'hello'))

  def test_path_dots_removal_error(self):
    p = Path(ResolvedBasePath('[CACHE]'))

    with self.assertRaisesRegex(ValueError, 'going above the base'):
      print(repr(p / '..'))

    with self.assertRaisesRegex(ValueError, 'going above the base'):
      print(repr(p / 'something' / '..///./..'))

  def test_path_join(self):
    """Tests for Path.join()."""
    base_path = Path(ResolvedBasePath('[START_DIR]'))
    reference_path = base_path.join('foo').join('bar')
    self.assertEqual(base_path / 'foo' / 'bar', reference_path)

  def test_is_parent_of(self):
    p = Path(ResolvedBasePath('[CACHE]'))

    self.assertTrue(p.is_parent_of(p / 'a'))
    self.assertTrue(p.is_parent_of(p / 'a' / 'b' / 'c'))
    self.assertTrue((p / 'a').is_parent_of(p / 'a' / 'b' / 'c'))

  def test_is_parent_of_mismatch(self):
    p1 = Path(ResolvedBasePath('[CACHE]'))
    p2 = Path(ResolvedBasePath('[CLEANUP]'))

    self.assertFalse(p1.is_parent_of(p2))
    self.assertFalse(p2.is_parent_of(p1))

  def test_is_parent_of_checkout(self):
    p1 = Path(CheckoutBasePath(), 'some')
    p2 = Path(ResolvedBasePath('[CACHE]'), 'builder', 'src', 'some', 'thing')

    with self.assertRaisesRegex(ValueError, 'checkout_dir is unset'):
      p1.is_parent_of(p2)
    with self.assertRaisesRegex(ValueError, 'checkout_dir is unset'):
      p2.is_parent_of(p1)

    CheckoutBasePath._resolved = Path(
        ResolvedBasePath('[CACHE]'), 'builder', 'src')

    self.assertTrue(p1.is_parent_of(p2))
    self.assertFalse(p2.is_parent_of(p1))

  def test_is_parent_of_checkout_mismatch(self):
    p1 = Path(CheckoutBasePath(), 'some')
    p2 = Path(ResolvedBasePath('[CLEANUP]'), 'unrelated')

    CheckoutBasePath._resolved = Path(
        ResolvedBasePath('[CACHE]'), 'builder', 'src')

    self.assertFalse(p1.is_parent_of(p2))
    self.assertFalse(p2.is_parent_of(p1))

  def test_is_parent_of_sanity(self):
    p = Path(ResolvedBasePath('[CLEANUP]'))
    self.assertFalse((p / 'a').is_parent_of(p / 'ab'))


class TestPathsPostGlobalInit(unittest.TestCase):
  """Test case for config_types.Path."""

  def tearDown(self):
    ResetGlobalVariableAssignments()
    return super().tearDown()


if __name__ == '__main__':
  test_env.main()
