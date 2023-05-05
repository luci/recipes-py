# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'assertions',
    'properties',
    'step',
]

def RunSteps(api):
  try:
    api.assertions.assertEquals(0, 1)
  except AttributeError as e:
    api.step('AttributeError', [])

def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.MustRun, 'AttributeError'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
