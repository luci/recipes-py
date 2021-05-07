#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""General tests during the python3 transition."""

import unittest

import test_env


class Py3Syntax(unittest.TestCase):
  def test_python3_syntax(self):
    pass


if __name__ == '__main__':
  test_env.main()
