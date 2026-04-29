# Copyright 2026 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'file',
    'path',
]


def RunSteps(api):
  filepath = api.path.start_dir / 'some_file'
  api.file.write_text('create file', filepath, 'content')

  # Check if it is executable (defaults to True in tests)
  is_exe = api.file.is_executable('check executable', filepath)
  assert is_exe is True

  # Check with false test data
  is_exe_false = api.file.is_executable(
      'check non-executable', filepath, test_data=False)
  assert is_exe_false is False


def GenTests(api):
  yield api.test('basic')
