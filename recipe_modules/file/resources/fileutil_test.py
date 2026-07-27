#!/usr/bin/env vpython3
# Copyright 2026 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Unit Tests for fileutil.py"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest import mock

import fileutil


def _win_normcase(path: str) -> str:
  return path.replace('/', '\\').lower()


class RmTreeTest(unittest.TestCase):

  @mock.patch('os.path.normcase', side_effect=_win_normcase)
  @mock.patch('sys.platform', 'win32')
  @mock.patch('os.path.exists', return_value=True)
  @mock.patch('subprocess.call', return_value=0)
  def test_rmtree_win32_trailing_backslash(self, mock_call, mock_exists, _):
    fileutil._RmTree(
        'C:\\b\\s\\w\\ir\\cache\\builder\\src\\out\\5f91-win-build-perf-\\')
    mock_call.assert_called_once_with([
        'cmd.exe', '/c', 'rd', '/q', '/s',
        '"c:\\b\\s\\w\\ir\\cache\\builder\\src\\out\\5f91-win-build-perf-"'
    ])

  @mock.patch('os.path.normcase', side_effect=_win_normcase)
  @mock.patch('sys.platform', 'win32')
  @mock.patch('os.path.exists', return_value=True)
  @mock.patch('subprocess.call', return_value=0)
  def test_rmtree_win32_trailing_slash(self, mock_call, mock_exists, _):
    fileutil._RmTree('C:/b/s/w/ir/cache/builder/src/out/5f91-win-build-perf-/')
    mock_call.assert_called_once_with([
        'cmd.exe', '/c', 'rd', '/q', '/s',
        '"c:\\b\\s\\w\\ir\\cache\\builder\\src\\out\\5f91-win-build-perf-"'
    ])

  @mock.patch('os.path.normcase', side_effect=_win_normcase)
  @mock.patch('sys.platform', 'win32')
  @mock.patch('os.path.exists', return_value=True)
  @mock.patch('subprocess.call', return_value=0)
  def test_rmtree_win32_no_trailing_slash(self, mock_call, mock_exists, _):
    fileutil._RmTree(
        'C:\\b\\s\\w\\ir\\cache\\builder\\src\\out\\5f91-win-build-perf-')
    mock_call.assert_called_once_with([
        'cmd.exe', '/c', 'rd', '/q', '/s',
        '"c:\\b\\s\\w\\ir\\cache\\builder\\src\\out\\5f91-win-build-perf-"'
    ])

  @mock.patch('os.path.normcase', side_effect=_win_normcase)
  @mock.patch('sys.platform', 'win32')
  @mock.patch('os.path.exists', return_value=True)
  def test_rmtree_win32_double_quotes_raise(self, mock_exists, _):
    with self.assertRaises(ValueError):
      fileutil._RmTree('C:\\path\\"with"\\quotes')


if __name__ == '__main__':
  if '-v' in sys.argv:
    logging.basicConfig(level=logging.DEBUG)
  unittest.main()
