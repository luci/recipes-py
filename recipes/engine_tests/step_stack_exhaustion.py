# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

from recipe_engine.util import InputPlaceholder
from recipe_engine.recipe_api import StepFailure

DEPS = [
  'step',
]

class BadPlaceholder(InputPlaceholder):
  def render(self, test):
    raise StepFailure("EXPLOSION")


def RunSteps(api):
  try:
    api.step('innocent step', ['echo', 'some', 'step'])

    ph = BadPlaceholder('name')
    ph.namespaces = ('fake', 'namespace')

    api.step('bad step', ['echo', ph])
  finally:
    api.step.active_result  # this will raise a ValueError

def GenTests(api):
  yield (
    api.test('basic') +
    api.expect_exception('ValueError')
  )

