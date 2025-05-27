# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process, recipe_api

DEPS = [
  'assertions',
  'cq',
  'properties',
]


@recipe_api.ignore_warnings('recipe_engine/CQ_MODULE_DEPRECATED')
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
