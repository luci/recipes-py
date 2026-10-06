#!/usr/bin/env vpython3
# Copyright 2018 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""General tests during the python3 transition."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import ast
import difflib
from lib2to3 import refactor
import linecache
import os
from typing import Any
import unittest
import warnings

from libfuturize import fixes
import test_env


def _py_files() -> Iterator[str]:
  for (dirpath, dirnames, filenames) in os.walk(test_env.ROOT_DIR):
    try:
      dirnames.remove('.recipe_deps')
    except ValueError:
      pass
    yield from (
        os.path.join(dirpath, n)
        for n in filenames
        if n.endswith('.py')
    )


class _2to3TestTool(refactor.RefactoringTool):
  def __init__(
      self, test_fail: Callable[[str], None], *args: Any, **kwargs: Any
  ) -> None:
    self.test_fail = test_fail
    super().__init__(*args, **kwargs)

  @staticmethod
  def diff_texts(a: str, b: str, filename: str) -> Iterator[str]:
    """Return a unified diff of two strings."""
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    return difflib.unified_diff(
        a_lines,
        b_lines,
        filename,
        filename,
        "(original)",
        "(refactored)",
        lineterm="",
    )

  def print_output(
      self, old_text: str, new_text: str, filename: str, equal: bool
  ) -> None:
    if equal:
      return
    self.test_fail('\n' + '\n'.join(self.diff_texts(
        old_text, new_text, filename)))


class Py3Syntax(unittest.TestCase):
  def test_python3_syntax(self) -> None:
    for fname in _py_files():
      with self.subTest(fname=fname):
        with open(fname) as sourcef:
          with warnings.catch_warnings(record=True) as warn_msgs:
            ast.parse(sourcef.read(), fname, type_comments=True,
                      feature_version=(3, 8))
        if warn_msgs:
          fmt = 'line {msg.lineno}: {category}: {msg.message}\n  {line}'
          self.fail('\n' + '\n'.join(
              fmt.format(
                  msg=msg,
                  category=msg.category.__name__,
                  line=linecache.getline(msg.filename, msg.lineno)
              ) for msg in warn_msgs
          ))

  def test_futurize_stage1(self) -> None:
    avail_fixes = (
        fixes.lib2to3_fix_names_stage1 | fixes.libfuturize_fix_names_stage1
    )
    tool = _2to3TestTool(self.fail, avail_fixes)

    for fname in _py_files():
      with self.subTest(fname=fname):
        with open(fname) as f:
          data = f.read()
        if '#py3Only\n' in data:
          continue  # this file has marked itself as python3-only compatible.
        # extra newline is cargo-culted from tool.refactor_file.
        tool.refactor_string(data+'\n', fname)


if __name__ == '__main__':
  test_env.main()
