# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that placeholders can't wreck the world by exhausting the step stack.
"""

from recipe_engine import post_process
from recipe_engine.util import InputPlaceholder
from recipe_engine.recipe_api import StepFailure

DEPS = [
  'step',
]

class BadPlaceholder(InputPlaceholder):
  def render(self, test):
    raise Exception("EXPLOSION")

  def __repr__(self):
    return '<BadPlaceholder>'


def RunSteps(api):
  api.step('innocent step', ['bash', '-c', "echo some step"])

  ph = BadPlaceholder('name')
  ph.namespaces = ('fake', 'namespace')

  api.step('bad step', ['echo', ph])
  raise ValueError('Never reached')   # pragma: no cover


def GenTests(api):
  yield (
    api.test('basic') +
    api.expect_exception('Exception') +
    api.post_process(post_process.ResultReason,
                     "Uncaught Exception: Exception('EXPLOSION',)") +
    api.post_process(post_process.DropExpectation)
  )

