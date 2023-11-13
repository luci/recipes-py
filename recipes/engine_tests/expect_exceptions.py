# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that tests with multiple exceptions are handled correctly."""

from recipe_engine import post_process

DEPS = []

def my_function(): # pragma: no cover
  exceptions = []
  for exc_type in (ValueError, TypeError):
    try:
      raise exc_type('BAD DOGE')
    except Exception as exc:
      exceptions.append(exc)

  if exceptions:
    raise ExceptionGroup('multiple exceptions', exceptions)


def RunSteps(api):
  my_function()


def GenTests(api):
  yield api.test(
      'basic',
      api.expect_exception('TypeError'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.StatusException),
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: ExceptionGroup('multiple exceptions', "
          "'[ValueError('BAD DOGE'), TypeError('BAD DOGE')]')"))
