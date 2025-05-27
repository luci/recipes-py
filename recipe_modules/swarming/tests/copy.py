# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

DEPS = [
    'assertions',
    'swarming',
]


def RunSteps(api):

  def basic_request():
    request = api.swarming.task_request()
    return request.with_slice(
        0, request[0].with_command(['echo', 'hi']).with_dimensions(
            pool='example.pool', os='Debian'))

  req1 = basic_request()
  slice1 = req1[0]
  req2 = req1.with_slice(
      0,
      slice1.with_command(slice1.command + ['-h']).with_env_vars(FOO='42'))
  # Made for crbug.com/1131821
  api.assertions.assertNotEqual(id(req1[0]), id(req2[0]))
  api.assertions.assertListEqual(req1[0].command, ['echo', 'hi'])
  api.assertions.assertListEqual(req2[0].command, ['echo', 'hi', '-h'])
  api.assertions.assertDictEqual(req1[0].env_vars, {})
  api.assertions.assertDictEqual(req2[0].env_vars, {'FOO': '42'})


def GenTests(api):
  yield (api.test('basic') + api.post_process(DropExpectation))
