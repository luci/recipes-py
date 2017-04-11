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
      api.step('wait a bit', ['sleep', '1'])

    # Prefix the name without indenting.
    with api.step.context({'name': 'attempt number'}):
      step_result = api.step('one', ['echo', 'herpy'])
      assert step_result.step['name'] == 'complicated thing.attempt number.one'
      api.step('two', ['echo', 'derpy'])

  # Outer nested step's status should not inherit from inner.
  with api.step.nest('inherit status') as nest_step:
    with api.step.nest('inner step') as other_nest_step:
      other_nest_step.presentation.status = api.step.EXCEPTION
  assert nest_step.presentation.status == api.step.SUCCESS

  # Change outer status after nesting is complete.
  with api.step.nest('versatile status') as nest_step:
    with api.step.nest('inner step'):
      with api.step.nest('even deeper'):
        pass
    nest_step.presentation.status = api.step.FAILURE
  assert nest_step.presentation.status == api.step.FAILURE

  api.step('simple thing', ['sleep', '1'])


def GenTests(api):
  yield api.test('basic')
