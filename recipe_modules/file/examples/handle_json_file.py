# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
]


def RunSteps(api):
  dest = api.path['start_dir'].join('some_file.json')
  data = {'is_json': True}

  api.file.write_json('write_json', dest, data)

  read_data = api.file.read_json('read_json', dest, test_data=data)

  assert read_data == data, (read_data, data)

def GenTests(api):
  yield api.test('basic')
  yield (
      api.test('failure')
      + api.step_data('read_json',
          api.file.read_json(errno_name='JSON READ FAILURE'))
  )