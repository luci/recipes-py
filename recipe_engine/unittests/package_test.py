#!/usr/bin/env python

import doctest
import os
import sys
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
THIRD_PARTY = os.path.join(ROOT_DIR, 'recipe_engine', 'third_party')
sys.path.insert(0, os.path.join(THIRD_PARTY, 'mock-1.0.1'))
sys.path.insert(0, THIRD_PARTY)
sys.path.insert(0, ROOT_DIR)

import mock
from recipe_engine import package

class MockIOThings(object):
  def setUp(self):
    self.mock_os_patcher = mock.patch('recipe_engine.package.os')
    self.mock_os = self.mock_os_patcher.start()
    self.mock_os.path.join = os.path.join
    self.mock_os.path.dirname = os.path.dirname
    self.mock_os.sep = os.sep

    self.mock_subprocess_patcher = mock.patch(
        'recipe_engine.package.subprocess')
    self.mock_subprocess = self.mock_subprocess_patcher.start()

  def tearDown(self):
    self.mock_subprocess_patcher.stop()
    self.mock_os_patcher.stop()


class TestGitRepoSpec(MockIOThings, unittest.TestCase):
  REPO_URL = 'https://funny.recipes/repo.git'
  def setUp(self):
    super(TestGitRepoSpec, self).setUp()

    self.repo_spec = package.GitRepoSpec(
      'funny_recipes',
      self.REPO_URL,
      'master',
      'deadbeef',
      'path/to/recipes',
    )
    self.context = package.PackageContext(
      recipes_dir='repo/root/recipes',
      package_dir='repo/root/recipes/.recipe_deps',
      repo_root='repo/root',
    )

  def test_checkout_nonexistant_package_dir(self):
    self.mock_os.path.exists.return_value = False
    self.mock_os.path.isdir.return_value = False

    self.repo_spec.checkout(self.context)

    self.mock_subprocess.check_call.assert_any_call(
        ['git', 'clone', self.REPO_URL,
         os.path.join(self.context.package_dir, 'funny_recipes')],
         cwd=None)
    self.mock_subprocess.check_call.assert_any_call(
        ['git', 'reset', '-q', '--hard', 'deadbeef'],
        cwd='repo/root/recipes/.recipe_deps/funny_recipes')


class MockProtoFile(package.ProtoFile):
  def __init__(self, path, text):
    super(MockProtoFile, self).__init__(path)
    self._text = text

  @property
  def path(self):
    return self._path

  def read_text(self):
    return self._text

  def write(self, buf):
    pass


class TestPackageSpec(MockIOThings, unittest.TestCase):
  def setUp(self):
    super(TestPackageSpec, self).setUp()

    self.proto_text = """
api_version: 1
project_id: "super_main_package"
recipes_path: "path/to/recipes"
deps {
  project_id: "bar"
  url: "https://repo.com/bar.git"
  branch: "superbar"
  revision: "deadd00d"
}
deps {
  project_id: "foo"
  url: "https://repo.com/foo.git"
  branch: "master"
  revision: "cafebeef"
}
""".lstrip()
    self.proto_file = MockProtoFile('repo/root/infra/config/recipes.cfg',
                                    self.proto_text)
    self.context = package.PackageContext.from_proto_file(
        'repo/root', self.proto_file)

  # def test_dump_load_inverses(self):
    # Doubles as a test for equality reflexivity.
    package_spec = package.PackageSpec.load_proto(self.proto_file)
    self.assertEqual(self.proto_file.to_text(package_spec.dump()),
                     self.proto_text)
    self.assertEqual(package.PackageSpec.load_proto(self.proto_file),
                     package_spec)

  def test_updates_merged(self):
    """Tests that updates are monotone in each dependency's history and
    that dep rolls stay in their proper dependency."""

    def trivial_proto(project_id):
      return lambda context: MockProtoFile('infra/config/recipes.cfg', """
api_version: 1
project_id: "%s"
recipes_path: ""
""".lstrip() % project_id)

    package_spec = package.PackageSpec.load_proto(self.proto_file)
    foo_revs = [ "aaaaaa", "123456", "cdabfe" ]
    bar_revs = [ "0156ff", "ffaaff", "aa0000" ]
    package_spec.deps['bar']._raw_updates = mock.Mock(
        return_value='\n'.join(bar_revs))
    package_spec.deps['bar'].proto_file = trivial_proto('bar')
    package_spec.deps['foo']._raw_updates = mock.Mock(
        return_value='\n'.join(foo_revs))
    package_spec.deps['foo'].proto_file = trivial_proto('foo')

    updates = package_spec.updates(self.context)
    foo_update_ixs = [
        (['cafebeef'] + foo_revs).index(update.spec.deps['foo'].revision)
        for update in updates ]
    bar_update_ixs = [
        (['deadd00d'] + bar_revs).index(update.spec.deps['bar'].revision)
        for update in updates ]
    self.assertEqual(len(updates), 6)
    self.assertEqual(foo_update_ixs, sorted(foo_update_ixs))
    self.assertEqual(bar_update_ixs, sorted(bar_update_ixs))

  def test_no_version(self):
    with self.assertRaises(Exception):
      package.PackageSpec.load({
          'id': 'foo',
          'deps': {},
      })

  def test_unsupported_version(self):
    with self.assertRaises(Exception):
      package.PackageSpec.load({
          'api_version': 1,
          'id': 'fizzbar',
          'deps': {},
      })

def load_tests(loader, tests, ignore):
  tests.addTests(doctest.DocTestSuite(package))
  return tests


if __name__ == '__main__':
  result = unittest.main()
