#!/usr/bin/env python
# Copyright 2016 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import os
import subprocess
import sys
import unittest

import test_env
import mock

from recipe_engine import package
from recipe_engine import autoroll

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
    self.assertEqual([], autoroll.process_rejected([]))

  def test_good_candidates(self):
    self.assertEqual(
        [
            'foobar',
            'theother',
            'thing',
        ],
        autoroll.process_rejected([
            FakeCandidate('foobar'),
            FakeCandidate('theother'),
            FakeCandidate('thing'),
        ]))

  def test_ignore_all_candidates(self):
    self.assertEqual(
        [],
        autoroll.process_rejected([
            FakeCandidate('foobar', ['depot_tools']),
        ], ['build']))

  def test_ignore_some_candidates(self):
    self.assertEqual(
        ['build', ],
        autoroll.process_rejected([
            FakeCandidate('build', ['build']),
            FakeCandidate('depot_tools', ['depot_tools']),
        ], ['build']))

if __name__ == '__main__':
  sys.exit(unittest.main())
