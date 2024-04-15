# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
  "json",
]


def RunSteps(api):
  dest = api.path.start_dir / 'some file'
  data = b'\xef\xbb\xbft'

  api.file.write_raw('write a file', dest, data)
  api.file.copy('copy it', dest, api.path.start_dir / 'new path')
  read_data = api.file.read_raw(
    'read it', api.path.start_dir / 'new path', test_data=data)

  assert read_data == data, (read_data, data)

  api.file.move('move it', api.path.start_dir / 'new path',
                api.path.start_dir / 'new new path')

  read_data = api.file.read_raw(
    'read it', api.path.start_dir / 'new new path', test_data=data)

  assert read_data == data, (read_data, data)


def GenTests(api):
  yield api.test('basic')
