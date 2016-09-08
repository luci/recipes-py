# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


DEPS = [
  'step',
]


def RunSteps(api):
  # Nest all steps below this.
  with api.step.nest('complicated thing'):
    with api.step.nest('first part'):
      api.step('wait a bit', ['sleep', '10'])

    # Prefix the name without indenting.
    with api.step.context({'name': 'attempt number'}):
      step_result = api.step('one', ['echo', 'herpy'])
      assert step_result.step['name'] == 'complicated thing.attempt number.one'
      api.step('two', ['echo', 'derpy'])

  api.step('simple thing', ['sleep', '10'])


def GenTests(api):
  yield api.test('basic')
