# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

DEPS = [
    'assertions',
    'path',
    'swarming',
]


def RunSteps(api):
  output_dir = api.path.mkdtemp('swarming')
  text_dir = api.path.mkdtemp('swarming')

  with api.assertions.assertRaises(ValueError):
    # Two Paths in task_output_stdout are not allowed.
    api.swarming.collect('collect', ['1234'],
                         output_dir=output_dir,
                         task_output_stdout=[output_dir, text_dir])

def GenTests(api):
  yield (api.test('basic') + api.post_process(DropExpectation))
