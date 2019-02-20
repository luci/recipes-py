#!/usr/bin/env vpython
# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import importlib
import os
import subprocess
import sys

import test_env

from recipe_engine.internal.commands.doc import cmd as doc


class DocSmokeTest(test_env.RecipeEngineUnitTest):
  def test_doc(self):
    nul = open(os.devnull, 'w')

    script_path = os.path.join(test_env.ROOT_DIR, 'recipes.py')
    exit_code = subprocess.call([sys.executable, script_path, 'doc'],
                                stdout=nul, stderr=nul)
    self.assertEqual(0, exit_code)


class TestMockImports(test_env.RecipeEngineUnitTest):
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
  test_env.main()
