#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
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

from recipe_engine import autoroll
from recipe_engine import common_args

def process_rejected(rejected_candidates):
  return [c.to_dict() for c in rejected_candidates]

class FakeCandidate(object):
  def __init__(self, data, projects=None):
    self._projects = projects
    self._data = data

  def get_affected_projects(self):
    return self._projects

  def to_dict(self):
    return self._data

class TestProcess(unittest.TestCase):
  def test_basic(self):
    self.assertEqual([], process_rejected([]))

  def test_good_candidates(self):
    self.assertEqual(
        [
            'foobar',
            'theother',
            'thing',
        ],
        process_rejected([
            FakeCandidate('foobar'),
            FakeCandidate('theother'),
            FakeCandidate('thing'),
        ]))


class TestArgs(unittest.TestCase):
  def setUp(self):
    self.p = argparse.ArgumentParser()
    self.followup = common_args.add_common_args(self.p)
    subp = self.p.add_subparsers()
    autoroll.add_subparser(subp)

    fd, self.tmpfile = tempfile.mkstemp()
    os.close(fd)

  def tearDown(self):
    os.remove(self.tmpfile)

  @mock.patch('argparse._sys.stderr', new_callable=StringIO)
  def test_json_flags(self, stderr):
    with self.assertRaises(SystemExit):
      args = self.p.parse_args(['autoroll', '--verbose-json'])
      args.postprocess_func(self.p, args)
    self.assertIn('without --output-json', stderr.getvalue())

    args = self.p.parse_args([
      'autoroll', '--verbose-json', '--output-json', self.tmpfile])
    args.postprocess_func(self.p, args)


if __name__ == '__main__':
  sys.exit(unittest.main())
