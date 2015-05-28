#!/usr/bin/env python
# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from recipe_engine import field_composer


# Functors are compared by reference.
BEAUTY_LAMBDA = lambda x, y: x + y + 1


class TestFieldComposer(unittest.TestCase):

  def setUp(self):
    super(TestFieldComposer, self).setUp()
    _functors = {
      'beauty': {'combine': BEAUTY_LAMBDA},
      'despair': {'combine': lambda x, y: x * y}}
    self.fc = field_composer.FieldComposer(
        {'beauty': 7, 'despair': 10}, _functors)

  def test_init_degenerate_registry(self):
    """Lack of 'combine' in registry value should raise an error."""
    with self.assertRaises(field_composer.DegenerateRegistryError):
      field_composer.FieldComposer(
          {'hello': 'hello'}, {'hello': {'darkness': 'my old friend'}})

  def test_dict_methods_ok(self):
    """FieldComposer acts as a dict for some methods."""
    for key in ['beauty', 'despair', 'absence']:
      # fc.get returns fc._fields.get
      self.assertEqual(self.fc._fields.get(key), self.fc.get(key))
      self.assertEqual(self.fc._fields.get(key, 1), self.fc.get(key, 1))

      # in fc returns in fc._fields
      self.assertEqual(key in self.fc, key in self.fc._fields)

      # fc[key] returns fc._fields[key]
      if key in self.fc:
        self.assertEqual(self.fc[key], self.fc._fields[key])
      else:
        with self.assertRaises(KeyError):
          _ = self.fc._fields[key]

  def test_compose_with_dict_ok(self):
    new_fields = {'beauty': 9}
    new_fc = self.fc.compose(new_fields)
    expected = {'beauty': 17, 'despair': 10}
    self.assertEqual(expected, new_fc._fields)

  def test_compose_with_unknown_field(self):
    """CompositionUndefined must be raised when kwargs don't have combiners."""
    with self.assertRaises(field_composer.CompositionUndefined):
      self.fc.compose({'beauty': 9, 'hope': 'none to speak of'})

  def test_compose_with_compositor_ok(self):
    second_fc = field_composer.FieldComposer(
        {'beauty': 9}, {'beauty': {'combine': BEAUTY_LAMBDA}})
    new_fc = self.fc.compose(second_fc)
    expected = {'beauty': 17, 'despair': 10}
    self.assertEqual(expected, new_fc._fields)

  def test_compose_with_sneaky_bad_registry(self):
    """RegistryConflict must be raised when functors clash."""
    second_fc = field_composer.FieldComposer(
        {}, {'beauty': {'combine': lambda x, y: 0}})
    with self.assertRaises(field_composer.RegistryConflict):
      self.fc.compose(second_fc)


if __name__ == '__main__':
  unittest.main()
