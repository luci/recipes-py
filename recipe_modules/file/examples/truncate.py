# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'file',
    'path',
]


def RunSteps(api):
  filepath = api.path.start_dir.join('some_file')
  size_mb = 300

  MBtoB = lambda x: x * 1024 * 1024
  BtoMB = lambda x: x / (1024 * 1024)

  api.file.truncate('truncate a file', filepath, size_mb)
  filesizes = api.file.filesizes(
      'size of some_file', [filepath], test_data=[MBtoB(size_mb)])
  assert filesizes[0] == MBtoB(size_mb), ("size is %sMB" % BtoMB(filesizes[0]))


def GenTests(api):
  yield api.test('basic')
