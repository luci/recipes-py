# Copyright 2022 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    "file",
    "path",
]


def RunSteps(api):
  api.file.write_text('Writing text to file.txt', 'file.txt', 'abcd')
  api.file.chmod('Changing file permissions for file.txt', 'file.txt', 0o777)

  try:
    api.file.chmod('File does not exist', 'non-existent-file.txt', 0o777)
  except Exception as e:
    assert isinstance(e, api.file.Error) and e.errno_name == 'ENOENT'


def GenTests(api):
  yield (api.test('basic') +
         api.step_data('File does not exist', api.file.errno('ENOENT')))
