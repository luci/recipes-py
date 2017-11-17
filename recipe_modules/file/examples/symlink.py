# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'file',
  'path',
  'json',
]


def RunSteps(api):
  dest = api.path['start_dir'].join('some file')
  data = 'Here is some text data'

  api.file.write_text('write a file', dest, data)
  api.file.symlink('symlink it', dest, api.path['start_dir'].join('new path'))
  read_data = api.file.read_text(
    'read it', api.path['start_dir'].join('new path'), test_data=data)

  assert read_data == data, (read_data, data)


def GenTests(api):
  yield api.test('basic')
