#!/usr/bin/env vpython
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import argparse
import os
import sys
import tempfile
import unittest

from cStringIO import StringIO

import mock

import test_env

from recipe_engine import test
from recipe_engine import common_args


class TestArgs(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    fd, cls.pkg_file = tempfile.mkstemp()
    os.write(fd, "{}")
    os.close(fd)

  @classmethod
  def tearDownClass(cls):
    os.remove(cls.pkg_file)

  def setUp(self):
    self.p = argparse.ArgumentParser()
    self.followup = common_args.add_common_args(self.p)
    subp = self.p.add_subparsers()
    test.add_subparser(subp)

  @mock.patch('argparse._sys.stderr', new_callable=StringIO)
  def test_normalize_filter(self, stderr):
    with self.assertRaises(SystemExit):
      args = self.p.parse_args([
        '--package', self.pkg_file, 'test', 'run',
        '--filter', ''])
      args.postprocess_func(self.p, args)
    self.assertIn('empty filters not allowed', stderr.getvalue())

    stderr.reset()
    args = self.p.parse_args(['--package', self.pkg_file, 'test', 'run',
                              '--filter', 'foo'])
    args.postprocess_func(self.p, args)
    self.assertEqual(args.filter, ['foo*.*'])

    stderr.reset()
    args = self.p.parse_args(['--package', self.pkg_file, 'test', 'run',
                              '--filter', 'foo.bar'])
    args.postprocess_func(self.p, args)
    self.assertEqual(args.filter, ['foo.bar'])


if __name__ == '__main__':
  sys.exit(unittest.main())

