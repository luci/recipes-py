# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  "file",
  "path",
]


def RunSteps(api):
  dest = api.path.start_dir / 'some_file.json'
  # Test a non-trivial number of keys in a dict.  This tests that the keys
  # are sorted in the output.
  data = {str('key%d' % i): True for i in range(10)}

  api.file.write_json('write_json', dest, data)

  read_data = api.file.read_json('read_json', dest, test_data=data)

  assert read_data == data, (read_data, data)

def GenTests(api):
  yield api.test('basic')
  yield api.test(
      'failure',
      api.step_data('read_json',
          api.file.read_json(errno_name='JSON READ FAILURE')),
      status='FAILURE',
  )
