# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "assertions",
  "file",
  "path",
]

def RunSteps(api):
  some_dir = api.path['start_dir'].join('some_dir')
  api.file.ensure_directory('ensure some_dir', some_dir)

  some_file = some_dir.join('some file')

  api.file.write_text('write some file', some_file, 'some data')

  result = api.file.file_hash(some_file,
                              test_data='deadbeef')
  expected = 'deadbeef'
  api.assertions.assertEqual(result, expected)

  another_file = api.path['start_dir'].join('another_file')
  api.file.write_text('write another file', another_file, 'some data')

  result = api.file.file_hash(another_file,
                              test_data='beefdead')
  expected = 'beefdead'
  api.assertions.assertEqual(result, expected)

  result = api.file.file_hash(another_file)
  expected = '02f88ac238b7aef5df694b0a14957d5a8da6ea88f4cc12ffa5ed56ad98dcc2ed'
  api.assertions.assertEqual(result, expected)


def GenTests(api):
  yield api.test('basic')
