# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
]


def RunSteps(api):
  root_dir = api.path['start_dir'].join('root_dir')
  api.file.ensure_directory('ensure root_dir', root_dir)

  listdir_result = api.file.listdir('listdir root_dir', root_dir, [])
  assert listdir_result == [], (listdir_result, [])

  some_file = root_dir.join('some file')
  api.file.write_text('write some file', some_file, 'some data')

  listdir_result = api.file.listdir('listdir root_dir', root_dir,
                                    ['some file'])
  assert listdir_result == [some_file], (listdir_result, [some_file])


def GenTests(api):
  yield api.test('basic')
