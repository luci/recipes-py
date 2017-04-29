#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import os
import sys
import tempfile
import unittest

from cStringIO import StringIO

import test_env

import argparse  # this is vendored

import mock

from recipe_engine import test
from recipe_engine import common_args


class TestArgs(unittest.TestCase):
  def setUp(self):
    self.p = argparse.ArgumentParser()
    self.followup = common_args.add_common_args(self.p)
    subp = self.p.add_subparsers()
    test.add_subparser(subp)

  @mock.patch('argparse._sys.stderr', new_callable=StringIO)
  def test_normalize_filter(self, stderr):
    with self.assertRaises(SystemExit):
      args = self.p.parse_args(['test', 'run', '--filter', ''])
      args.postprocess_func(self.p, args)
    self.assertIn('empty filters not allowed', stderr.getvalue())

    stderr.reset()
    args = self.p.parse_args(['test', 'run', '--filter', 'foo'])
    args.postprocess_func(self.p, args)
    self.assertEqual(args.filter, ['foo*.*'])

    stderr.reset()
    args = self.p.parse_args(['test', 'run', '--filter', 'foo.bar'])
    args.postprocess_func(self.p, args)
    self.assertEqual(args.filter, ['foo.bar'])

  def test_automatic_bootstrap(self):
    with tempfile.NamedTemporaryFile('w', delete=False) as tf:
      tf.write("""{
        "api_version": 2,
        "project_id": "fake",
      }""")

    try:
      args = self.p.parse_args(['--package', tf.name, 'test', 'run'])
      self.assertIsNone(args.use_bootstrap)
      self.followup(self.p, args)
      args.postprocess_func(self.p, args)
      self.assertTrue(args.use_bootstrap)
    finally:
      os.remove(tf.name)


if __name__ == '__main__':
  sys.exit(unittest.main())

