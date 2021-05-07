#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""General tests during the python3 transition."""

import ast
import linecache
import os
import unittest
import warnings

import test_env


class Py3Syntax(unittest.TestCase):
  def test_python3_syntax(self):
    for (dirpath, _, filenames) in os.walk(test_env.ROOT_DIR):
      py_files = (os.path.join(dirpath, n) for n in filenames if
                     n.endswith('.py'))
      for fname in py_files:
        with self.subTest(fname=fname):
          with open(fname) as sourcef:
            with warnings.catch_warnings(record=True) as warn_msgs:
              ast.parse(sourcef.read(), fname, type_comments=True,
                        feature_version=(3, 8))
          if warn_msgs:
            fmt = 'line {msg.lineno}: {category}: {msg.message}\n  {line}'
            self.fail('\n' + '\n'.join(
                fmt.format(
                    msg=msg,
                    category=msg.category.__name__,
                    line=linecache.getline(msg.filename, msg.lineno)
                ) for msg in warn_msgs
            ))


if __name__ == '__main__':
  test_env.main()
