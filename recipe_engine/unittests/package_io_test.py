#!/usr/bin/env python
# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import json
import sys
import unittest

import test_env

from recipe_engine import package_io
from recipe_engine import package_pb2

class TestPackageIO(unittest.TestCase):
  def setUp(self):
    autoroll_options = {
      'trivial': {
        'tbr_emails': ['foo@example.com', 'bar@example.com'],
        'automatic_commit': True,
      },
      'nontrivial': {
        'extra_reviewer_emails': ['foo@example.com', 'bar@example.com'],
        'automatic_commit_dry_run': True,
      },
      'disable_reason': 'a really good one',
    }

    dep1 = {
      'project_id': 'dep1',
      'url': 'https://dep1.example.com',
      'branch': 'master',
      'revision': 'a'*40,
      'path_override': 'sub/path',
      'repo_type': 'GITILES',
    }

    self.raw_v1 = json.dumps({
      'api_version': 1,
      'project_id': 'test',
      'canonical_repo_url': 'https://canonical.example.com',
      'recipes_path': 'foo/bar',
      'deps': [dict(dep1)],
      'autoroll_recipe_options': autoroll_options,
    }, indent=2, sort_keys=True).replace(' \n', '\n')

    dep1.pop('project_id')

    self.raw_v2 = json.dumps({
      'api_version': 2,
      'project_id': 'test',
      'canonical_repo_url': 'https://canonical.example.com',
      'recipes_path': 'foo/bar',
      'deps': {
        'dep1': dep1,
      },
      'autoroll_recipe_options': autoroll_options,
    }, indent=2, sort_keys=True).replace(' \n', '\n')

    self.parsed = package_pb2.Package(
      project_id='test',
      canonical_repo_url='https://canonical.example.com',
      recipes_path='foo/bar',
      deps={
        'dep1': package_pb2.DepSpec(
          url='https://dep1.example.com',
          branch='master',
          revision='a'*40,
          path_override='sub/path',
          repo_type=package_pb2.DepSpec.GITILES,
        ),
      },
      autoroll_recipe_options=package_pb2.AutorollRecipeOptions(
        trivial=package_pb2.AutorollRecipeOptions.TrivialOptions(
          tbr_emails=['foo@example.com', 'bar@example.com'],
          automatic_commit=True,
        ),
        nontrivial=package_pb2.AutorollRecipeOptions.NontrivialOptions(
          extra_reviewer_emails=['foo@example.com', 'bar@example.com'],
          automatic_commit_dry_run=True,
        ),
        disable_reason='a really good one',
      ),
    )


  def test_parse_v1(self):
    self.parsed.api_version = 1
    self.assertEqual(package_io.parse(self.raw_v1), self.parsed)

  def test_dump_v1(self):
    self.parsed.api_version = 1
    self.assertEqual(package_io.dump(self.parsed), self.raw_v1)

  def test_parse_v2(self):
    self.parsed.api_version = 2
    self.assertEqual(package_io.parse(self.raw_v2), self.parsed)

  def test_dump_v2(self):
    self.parsed.api_version = 2
    self.assertEqual(package_io.dump(self.parsed), self.raw_v2)


if __name__ == '__main__':
  sys.exit(unittest.main())

