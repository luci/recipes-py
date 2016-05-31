# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'properties',
    'step',
]

RETURN_SCHEMA = config.ReturnSchema(
  result=config.Single(int),
)


def RunSteps(api):
  api.step('bam', ['bingo'])
  # No return on purpose

def GenTests(api):
  yield (
      api.test('basic') +
      api.expect_exception('ValueError')
  )
