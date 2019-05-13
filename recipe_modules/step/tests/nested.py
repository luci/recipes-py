# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


DEPS = [
  'context',
  'step',
]


def RunSteps(api):
  # Nest all steps below this.
  with api.step.nest('complicated thing'):
    with api.step.nest('first part'):
      api.step('wait a bit', ['sleep', '1'])

    # Prefix the name without indenting.
    with api.context(name_prefix='attempt number: '):
      step_result = api.step('one', ['echo', 'herpy'])
      sc = step_result.step_config
      expected_name = ('complicated thing', 'attempt number: one')
      assert sc.name_tokens == expected_name, sc.name_tokens
      api.step('two', ['echo', 'derpy'])

  # Outer nested step's status should not inherit from inner.
  with api.step.nest('inherit status') as nest_step:
    with api.step.nest('inner step') as other_nest_step:
      other_nest_step.presentation.status = api.step.EXCEPTION
  assert nest_step.presentation.status == api.step.SUCCESS, \
    nest_step.presentation.status

  # Change outer status after nesting is complete.
  with api.step.nest('versatile status') as nest_step:
    with api.step.nest('inner step'):
      with api.step.nest('even deeper'):
        pass
    nest_step.presentation.status = api.step.FAILURE
  assert nest_step.presentation.status == api.step.FAILURE, \
    nest_step.presentation.status

  # Duplicate nesting names with unique child steps
  for i in xrange(3):
    with api.step.nest('Do Iteration'):
      api.step('Iterate %d' % i, ['echo', 'lerpy'])

  api.step('simple thing', ['sleep', '1'])

  # Show interaction between name_prefix and namespace.
  with api.context(name_prefix='cool '):
    api.step('something', ['echo', 'something'])

    with api.context(namespace='world', name_prefix='hot '):
      api.step('other', ['echo', 'other'])

      with api.context(name_prefix='tamale '):
        api.step('yowza', ['echo', 'yowza'])

    with api.context(namespace='ocean'):
      api.step('mild', ['echo', 'mild'])

  # Note that "|" is a reserved character:
  try:
    api.step('cool|step', ['echo', 'hi'])
    assert False  # pragma: no cover
  except ValueError:
    pass


def GenTests(api):
  yield api.test('basic')
