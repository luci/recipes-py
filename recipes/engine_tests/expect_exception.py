# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that tests with a single exception are handled correctly."""

from recipe_engine import post_process

DEPS = [
]

def my_function(): # pragma: no cover
  raise TypeError("BAD DOGE")


def RunSteps(api):
  my_function()


def GenTests(api):
  yield (api.test('basic') + api.expect_exception('TypeError') +
         api.post_process(post_process.StatusException) +
         api.post_process(post_process.SummaryMarkdown,
                          "Uncaught Exception: TypeError('BAD DOGE')"))
