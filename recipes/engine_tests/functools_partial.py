"""Engine shouldn't explode when step_test_data gets functools.partial.

This is a regression test for a bug caused by this revision:
http://src.chromium.org/viewvc/chrome?revision=298072&view=revision

When this recipe is run (by run_test.py), the _print_step code is exercised.
"""

import functools
from recipe_engine import recipe_test_api

DEPS = ['step']

def RunSteps(api):
  api.step('Here\'s a step brah', ['echo', 'steppity', 'doo', 'dah'],
           step_test_data=functools.partial(
              lambda x: recipe_test_api.StepTestData(), None))

def GenTests(api):
  yield api.test('basic')
