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

  listdir_result = api.file.listdir('listdir root_dir', root_dir, test_data=[])
  assert listdir_result == [], (listdir_result, [])

  some_file = root_dir.join('some file')
  sub_dir = root_dir.join('sub')
  in_subdir = sub_dir.join('f')

  api.file.write_text('write some file', some_file, 'some data')
  api.file.ensure_directory('mkdir', sub_dir)
  api.file.write_text('write another file', in_subdir, 'some data')

  result = api.file.listdir('listdir root_dir', root_dir,
                            test_data=['some file', 'sub'])
  expected = [some_file, sub_dir]
  assert result == expected, (result, expected)

  result = api.file.listdir('listdir root_dir', root_dir,
                            recursive=True,
                            test_data=['some file', 'sub/f'])
  expected = [some_file, in_subdir]
  assert result == expected, (result, expected)


def GenTests(api):
  yield api.test('basic')
