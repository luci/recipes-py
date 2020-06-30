# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

from recipe_engine import post_process

DEPS = [
  'step',
]

def RunSteps(api):
  raise TypeError("BAD DOGE")

def GenTests(api):
  yield (
    api.test('basic') +
    api.expect_exception('TypeError') +
    api.post_process(post_process.ResultReason,
                     "Uncaught Exception: TypeError('BAD DOGE',)") +
    api.post_process(post_process.DropExpectation)
  )
