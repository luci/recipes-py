# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.recipe_modules.recipe_engine.file.examples.read_write_proto import SomeMessage

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
  "file",
  "path",
  "proto",
]


def RunSteps(api):
  msg = SomeMessage(fields=['abc', 'def'])

  dest = api.path['start_dir'].join('message.textproto')
  api.file.write_proto('write_proto', dest, msg, 'TEXTPB')

  read_msg = api.file.read_proto(
      'read_proto',
      dest,
      SomeMessage,
      'TEXTPB',
      test_proto=msg)

  assert read_msg == msg, (read_msg, msg)

  # read_proto call without test_proto, for test coverage.
  read_msg_again = api.file.read_proto(
      'read_proto_again',
      dest,
      SomeMessage,
      'TEXTPB')

def GenTests(api):
  yield api.test('basic')
  read_proto_data = api.file.read_proto(SomeMessage(fields=['abc', 'def']))
  yield (api.test('override_step_data')
         + api.override_step_data('read_proto_again', read_proto_data))
