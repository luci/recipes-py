# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
"""Tweaks sys.path to allow recipe_engine to be importable in tests.

Provides testing fakes for RecipeDeps, useful for all recipe subcommands.
"""

import atexit
import errno
import logging
import os
import shutil
import sys
import tempfile
import unittest


# Allow `recipe_engine` module to be importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# pylint: disable=wrong-import-position
from recipe_engine.internal.recipe_deps import RecipeDeps
from recipe_engine.util import fix_json_object

# Will compile all recipe protos and add them to sys.path as a side effect.
_ = RecipeDeps.create(ROOT_DIR, {}, None)
# Assert that the protos actually were compiled and are in path.
try:
  # pylint: disable=unused-import
  from PB.recipe_engine import recipes_cfg
except ImportError as exc:
  print('Failed to import `PB` with sys.path: ', sys.path)
  for path in sys.path:
    if path.endswith('_pb%d' % sys.version_info[0]):
      print('%r contains:' % (path,))
      for entry in os.listdir(path):
        print('  %r: %r' % (entry, os.stat(os.path.join(path, entry))))
  raise

from fake_recipe_deps import FakeRecipeDeps
from mock_recipe_deps import MockRecipeDeps


class CapturableHandler(logging.StreamHandler):
  """Allows unittests to capture log output.

  From: http://stackoverflow.com/a/33271004
  """
  @property
  def stream(self):
    return sys.stdout

  @stream.setter
  def stream(self, value):
    pass


# If --leak is passed on the command line, any artifacts from failing tests will
# be leaked.
LEAK='--leak' in sys.argv
if LEAK:
  sys.argv.remove('--leak')
  LEAKED_FILES = []
  LEAKED_DIRS = []
  def _print_leakage():
    if LEAKED_DIRS or LEAKED_FILES:
      print()
      print('*' * 8)
    if LEAKED_FILES:
      print('LEAKED the following files:')
      for f in LEAKED_FILES:
        print('  ', f)
    if LEAKED_DIRS:
      print('LEAKED the following dirs:')
      for f in LEAKED_DIRS:
        print('  ', f)
  atexit.register(_print_leakage)


class RecipeEngineUnitTest(unittest.TestCase):
  def setUp(self):
    self.maxDiff = None
    self.nuke_dirs = []
    self.nuke_files = []

  def tearDown(self):
    if LEAK and not self._resultForDoCleanups.wasSuccessful():
      LEAKED_DIRS.extend(self.nuke_dirs)
      LEAKED_FILES.extend(self.nuke_files)
      return

    for to_nuke in self.nuke_dirs:
      shutil.rmtree(to_nuke, ignore_errors=True)
    for to_nuke in self.nuke_files:
      try:
        os.unlink(to_nuke)
      except OSError as ex:
        if ex.errno != errno.ENOENT:
          raise

  def tempfile(self):
    fd, path = tempfile.mkstemp('.recipe_engine_tests')
    os.close(fd)
    path = os.path.realpath(path)
    self.nuke_files.append(path)
    return path

  def tempdir(self):
    path = os.path.realpath(tempfile.mkdtemp('.recipe_engine_tests'))
    self.nuke_dirs.append(path)
    return path

  def assertDictEqual(self, d1, d2, msg=None):
    """Override the parent's assertDictEqual to strip out unicode objects.

    This leads to much more readable diffs when debugging tests."""
    super(RecipeEngineUnitTest, self).assertDictEqual(
        fix_json_object(d1), fix_json_object(d2),
        msg)

  def assertListEqual(self, d1, d2, msg=None):
    """Override the parent's assertListEqual to strip out unicode objects.

    This leads to much more readable diffs when debugging tests."""
    super(RecipeEngineUnitTest, self).assertListEqual(
        fix_json_object(d1), fix_json_object(d2),
        msg)


  def FakeRecipeDeps(self):
    """Creates an empty FakeRecipeDeps.

    Returns a FakeRecipeDeps object.
    """
    return FakeRecipeDeps(self.tempdir())

  @staticmethod
  def MockRecipeDeps(modules_to_DEPS=None, recipes_to_DEPS=None):
    """Creates a MockRecipeDeps.

    Returns a MockRecipeDeps object.
    """
    return MockRecipeDeps(modules_to_DEPS, recipes_to_DEPS)


def main():
  if '-v' in sys.argv or '--verbose' in sys.argv:
    logging.root.handlers=[CapturableHandler()]
    logging.basicConfig(level=logging.DEBUG)
  sys.exit(unittest.main())
