#!/usr/bin/env python
# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import copy
import doctest
import logging
import os
import subprocess
import sys
import unittest

import repo_test_util

import mock

from recipe_engine import fetch
from recipe_engine import package
from recipe_engine import package_io

TEST_AUTHOR = 'foo@example.com'


class MockIOThings(object):
  def setUp(self):
    super(MockIOThings, self).setUp()

    self.mock_os_patcher = mock.patch('recipe_engine.package.os')
    self.mock_os = self.mock_os_patcher.start()
    self.mock_os.path.join = os.path.join
    self.mock_os.path.dirname = os.path.dirname
    self.mock_os.sep = os.sep

    self.orig_subprocess = subprocess
    self.mock_subprocess_patcher = mock.patch(
        'recipe_engine.package.subprocess')
    self.mock_subprocess = self.mock_subprocess_patcher.start()
    self.mock_subprocess.PIPE = self.orig_subprocess.PIPE

  def tearDown(self):
    self.mock_subprocess_patcher.stop()
    self.mock_os_patcher.stop()

    super(MockIOThings, self).tearDown()


class TestGitRepoSpec(repo_test_util.RepoTest):
  def test_updates(self):
    self._context.allow_fetch = True
    repos = self.repo_setup({'a': []})

    spec = self.get_git_repo_spec(repos['a'])
    self.assertEqual([], spec.updates())

    revs = lambda cmetas: [m.revision for m in cmetas]

    c1 = self.commit_in_repo(repos['a'], message='c1')
    self.assertEqual([
        c1['revision']],
        revs(spec.updates()))

    c2 = self.commit_in_repo(repos['a'], message='c2')
    self.assertEqual([
        c1['revision'], c2['revision']],
        revs(spec.updates()))

    c3 = self.commit_in_repo(repos['a'], message='c3')
    self.assertEqual([
        c1['revision'], c2['revision'], c3['revision']],
        revs(spec.updates()))


class MockPackageFile(package_io.PackageFile):
  def __init__(self, path, text):
    self._text = text
    super(MockPackageFile, self).__init__(path)

  @property
  def path(self):
    return self._path

  def read_raw(self):
    return self._text

  def write(self, buf):
    pass


class TestPackageSpec(MockIOThings, unittest.TestCase):
  def setUp(self):
    super(TestPackageSpec, self).setUp()

    self.proto_text = '\n'.join([
      '{',
      '  "api_version": 2,',
      '  "deps": {',
      '    "bar": {',
      '      "branch": "superbar",',
      '      "revision": "deadd00d",',
      '      "url": "https://repo.com/bar.git"',
      '    },',
      '    "foo": {',
      '      "branch": "master",',
      '      "revision": "cafebeef",',
      '      "url": "https://repo.com/foo.git"',
      '    }',
      '  },',
      '  "project_id": "super_main_package",',
      '  "recipes_path": "path/to/recipes"',
      '}',
    ])
    self.package_file = MockPackageFile('repo/root/infra/config/recipes.cfg',
                                        self.proto_text)
    self.context = package.PackageContext.from_package_pb(
        'repo/root', self.package_file.read(), allow_fetch=False)

  def test_dump_load_inverses(self):
    # Doubles as a test for equality reflexivity.
    package_spec = package.PackageSpec.from_package_pb(
      self.context, self.package_file.read())
    self.assertEqual(self.package_file.to_raw(package_spec.spec_pb),
                     self.proto_text)
    self.assertEqual(package.PackageSpec.from_package_pb(
      self.context, self.package_file.read()), package_spec)

  def test_dump_round_trips(self):
    proto_text = """
{"api_version": 1}
""".lstrip()
    package_file = MockPackageFile('repo/root/infra/config/recipes.cfg',
                                   proto_text)
    package_spec = package.PackageSpec.from_package_pb(
      self.context, package_file.read())
    self.assertEqual(package_file.to_raw(package_spec.spec_pb),
                     '{\n  "api_version": 1\n}')

  def test_no_version(self):
    proto_text = """{
  "project_id": "foo",
  "recipes_path": "path/to/recipes"
}
"""
    package_file = MockPackageFile('repo/root/infra/config/recipes.cfg',
                                   proto_text)

    with self.assertRaises(AssertionError):
      package.PackageSpec.from_package_pb(self.context, package_file.read())

  def test_old_deps(self):
    proto_text = '\n'.join([
      '{',
      '  "api_version": 1,',
      '  "deps": [',
      '    {',
      '      "branch": "superbar",',
      '      "project_id": "bar",',
      '      "revision": "deadd00d",',
      '      "url": "https://repo.com/bar.git"',
      '    },',
      '    {',
      '      "branch": "master",',
      '      "project_id": "foo",',
      '      "revision": "cafebeef",',
      '      "url": "https://repo.com/foo.git"',
      '    }',
      '  ],',
      '  "project_id": "super_main_package",',
      '  "recipes_path": "path/to/recipes"',
      '}',
    ])
    package_file = MockPackageFile('repo/root/infra/config/recipes.cfg',
                                   proto_text)

    spec = package.PackageSpec.from_package_pb(
      self.context, package_file.read())
    self.assertEqual(spec.deps['foo'], package.GitRepoSpec(
      'foo',
      'https://repo.com/foo.git',
      'master',
      'cafebeef',
      '',
      fetch.GitBackend('', '', False)
    ))
    self.assertEqual(package_file.to_raw(spec.spec_pb), proto_text)


  def test_unsupported_version(self):
    proto_text = """{
  "api_version": 99999999,
  "project_id": "fizzbar",
  "recipes_path": "path/to/recipes"
}"""
    package_file = MockPackageFile('repo/root/infra/config/recipes.cfg',
                                   proto_text)

    with self.assertRaises(AssertionError):
      package.PackageSpec.from_package_pb(self.context, package_file.read())


class TestPackageDeps(MockIOThings, unittest.TestCase):

  def test_create_with_overrides(self):
    base_proto_text = """{
  "api_version": 1,
  "project_id": "base_package",
  "recipes_path": "path/to/recipes",
  "deps": [
    {
      "project_id": "foo",
      "url": "https://repo.com/foo.git",
      "branch": "foobranch",
      "revision": "deadd00d"
    }
  ]
}
"""
    base_package_file = MockPackageFile('base/infra/config/recipes.cfg',
                                        base_proto_text)

    foo_proto_text = """{
  "api_version": 1,
  "project_id": "foo",
  "recipes_path": "path/to/recipes"
}"""
    foo_package_file = MockPackageFile('foo/infra/config/recipes.cfg',
                                       foo_proto_text)

    with mock.patch.object(package.GitRepoSpec, 'checkout') as checkout:
      with mock.patch.object(package.PathRepoSpec, 'spec_pb',
                             return_value=foo_package_file.read()):
        deps = package.PackageDeps.create('base', base_package_file, overrides={
          'foo': '/path/to/local/foo',
        })

      foo_deps = deps.get_package('foo')
      self.assertIsInstance(foo_deps.repo_spec, package.PathRepoSpec)
      self.assertEqual(foo_deps.repo_spec.path, '/path/to/local/foo')
      self.assertFalse(checkout.called)


def load_tests(_loader, tests, _ignore):
  tests.addTests(doctest.DocTestSuite(package))
  return tests


if __name__ == '__main__':
  if '-v' in sys.argv:
    logging.basicConfig(
      level=logging.DEBUG,
      handler=repo_test_util.CapturableHandler())
  result = unittest.main()
