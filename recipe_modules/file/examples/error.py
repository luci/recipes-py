# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  "file",
  "path",
]


def RunSteps(api):
  try:
    api.file.read_text(
      'does not exist', api.path['start_dir'].join('not_there'))
    assert False, "never reached"  # pragma: no cover
  except api.file.Error as e:
    assert e.errno_name == 'ENOENT'


def GenTests(api):
  yield (
    api.test('basic')
    + api.step_data('does not exist', api.file.errno('ENOENT'))
  )
