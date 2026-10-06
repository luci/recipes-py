# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.
from __future__ import annotations

"""Tweaks sys.path to allow recipe_engine to be importable in tests.

Provides testing fakes for RecipeDeps, useful for all recipe subcommands.
"""

from collections.abc import Mapping, Sequence
import atexit
import errno
import logging
import os
import shutil
import sys
import tempfile
from typing import Any, TextIO
import unittest

# Allow `recipe_engine` module to be importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# pylint: disable=wrong-import-position
from recipe_engine import util
from recipe_engine.internal import recipe_deps

# Will compile all recipe protos and add them to sys.path as a side effect.
_ = recipe_deps.RecipeDeps.create(ROOT_DIR, {}, None)
# Assert that the protos actually were compiled and are in path.
try:
  # pylint: disable=unused-import
  from PB.recipe_engine import recipes_cfg as recipes_cfg_pb
except ImportError as exc:
  print('Failed to import `PB` with sys.path: ', sys.path)
  for path in sys.path:
    if path.endswith('_pb%d' % sys.version_info[0]):
      print('%r contains:' % (path,))
      for entry in os.listdir(path):
        print('  %r: %r' % (entry, os.stat(os.path.join(path, entry))))
  raise

import fake_recipe_deps
import mock_recipe_deps


class CapturableHandler(logging.StreamHandler):
  """Allows unittests to capture log output.

  From: http://stackoverflow.com/a/33271004
  """

  @property
  def stream(self) -> TextIO:
    return sys.stdout

  @stream.setter
  def stream(self, value: TextIO) -> None:
    pass


# If --leak is passed on the command line, any artifacts from failing tests will
# be leaked.
LEAK = '--leak' in sys.argv
if LEAK:
  sys.argv.remove('--leak')
  LEAKED_FILES: list[str] = []
  LEAKED_DIRS: list[str] = []

  def _print_leakage() -> None:
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

  def setUp(self) -> None:
    self.maxDiff = None
    self.nuke_dirs: list[str] = []
    self.nuke_files: list[str] = []

  def tearDown(self) -> None:
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

  def tempfile(self) -> str:
    fd, path = tempfile.mkstemp('.recipe_engine_tests')
    os.close(fd)
    path = os.path.realpath(path)
    self.nuke_files.append(path)
    return path

  def tempdir(self) -> str:
    path = os.path.realpath(tempfile.mkdtemp('.recipe_engine_tests'))
    self.nuke_dirs.append(path)
    return path

  def assertDictEqual(
      self, d1: Mapping[Any, Any], d2: Mapping[Any, Any], msg: Any = None
  ) -> None:
    """Override the parent's assertDictEqual to strip out unicode objects.

    This leads to much more readable diffs when debugging tests.
    """
    super().assertDictEqual(
        util.fix_json_object(d1), util.fix_json_object(d2), msg
    )

  def assertListEqual(
      self, d1: list[Any], d2: list[Any], msg: Any = None
  ) -> None:
    """Override the parent's assertListEqual to strip out unicode objects.

    This leads to much more readable diffs when debugging tests.
    """
    super().assertListEqual(
        util.fix_json_object(d1), util.fix_json_object(d2), msg
    )

  def FakeRecipeDeps(self) -> fake_recipe_deps.FakeRecipeDeps:
    """Creates an empty FakeRecipeDeps.

    Returns a FakeRecipeDeps object.
    """
    return fake_recipe_deps.FakeRecipeDeps(self.tempdir())

  @staticmethod
  def MockRecipeDeps(
      modules_to_DEPS: Mapping[str, mock_recipe_deps.DepsSpec] | None = None,
      recipes_to_DEPS: Mapping[str, mock_recipe_deps.DepsSpec] | None = None,
  ) -> mock_recipe_deps.MockRecipeDeps:
    """Creates a MockRecipeDeps.

    Returns a MockRecipeDeps object.
    """
    return mock_recipe_deps.MockRecipeDeps(modules_to_DEPS, recipes_to_DEPS)


def main() -> None:
  if '-v' in sys.argv or '--verbose' in sys.argv:
    # _MAX_LENGTH is hard coded to 80 for some reason and so ends up truncating
    # comparison messages.
    __import__('sys').modules['unittest.util']._MAX_LENGTH = 999999999
    logging.root.handlers = [CapturableHandler()]
    logging.basicConfig(level=logging.DEBUG)
  sys.exit(unittest.main())
