# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine import config

DEPS = [
    'raw_io',
    'properties',
    'step',
]

PROPERTIES = {
    'number': Property(kind=int),
}

RETURN_SCHEMA = config.ReturnSchema(
    number_times_two=config.Single(int),
)

def RunSteps(api, number):
  # Newline cause bc complains if it doesn't have it
  num_s = '%s*%s\n' % (number, 2)
  result = api.step(
      'calc it', ['bc'],
      stdin=api.raw_io.input(data=num_s),
      stdout=api.raw_io.output('out'))
  return RETURN_SCHEMA(number_times_two=int(result.stdout))

def GenTests(api):
  yield (
      api.test('basic') +
      api.properties(number=3) +
      api.step_data('calc it',
                    stdout=api.raw_io.output('6'))
  )
