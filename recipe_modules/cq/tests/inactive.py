# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
  'assertions',
  'cq',
  'properties',
]


def RunSteps(api):
  api.assertions.assertFalse(api.cq.active)


def GenTests(api):
  yield (
    api.test('no cq properties')
    + api.post_process(post_process.DropExpectation)
  )
  yield (
    api.test('empty cq properties')
    + api.properties(**{'$recipe_engine/cq': {}})
    + api.post_process(post_process.DropExpectation)
  )
