#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import importlib
import sys
import unittest

import test_env

from recipe_engine import doc


class TestMockImports(unittest.TestCase):
  def test_all_mock_imports_importable(self):
    for imp_name in doc.ALL_IMPORTS:
      if '.' in imp_name:
        mod, obj = imp_name.rsplit('.', 1)
      else:
        mod = imp_name
        obj = None
      try:
        m = importlib.import_module(mod)
        if obj and not hasattr(m, obj):
          self.fail('expected to find %r in %r', obj, mod)
      except Exception as ex:
        self.fail('failed to import %r: %s' % (mod, ex))


if __name__ == '__main__':
  sys.exit(unittest.main())
