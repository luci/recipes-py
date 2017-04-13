#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import sys
import unittest

import test_env

from recipe_engine import autoroll

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


if __name__ == '__main__':
  sys.exit(unittest.main())
