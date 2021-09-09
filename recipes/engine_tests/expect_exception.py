# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

from recipe_engine import post_process
from recipe_engine.recipe_api import composite_step

DEPS = [
]

# note that the frames from composite_step are omitted in the stack during
# training.
@composite_step
def my_function(): # pragma: no cover
  raise TypeError("BAD DOGE")


def RunSteps(api):
  my_function()


def GenTests(api):
  yield api.test(
      'basic',
      api.expect_exception('TypeError'),
      api.post_process(post_process.ResultReason,
                       "Uncaught Exception: TypeError('BAD DOGE')"))
