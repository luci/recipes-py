# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.post_process import StepSuccess, StepFailure, StepException


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
      name_tokens = step_result.name_tokens
      expected_name = ('complicated thing', 'attempt number: one')
      assert name_tokens == expected_name, name_tokens
      api.step('two', ['echo', 'derpy'])

  # Outer nested step's status gets the worst child's status by default.
  with api.step.nest('inherit status'):
    with api.step.nest('inner step') as other_nest_step:
      other_nest_step.presentation.status = api.step.EXCEPTION

  # But, you could also pick the last status.
  with api.step.nest('last status', status='last'):
    with api.step.nest('failpants') as other_nest_step:
      other_nest_step.presentation.status = api.step.EXCEPTION
    api.step('everything OK', ['echo', 'hi'])

  # Or, even add a callback
  with api.step.nest('callback status') as nest_step:
    def _callback(presentation, _nest_data):
      # Presumably this would actually combine the result of some other steps
      # inside nest_step.
      presentation.status = 'FAILURE'
    nest_step.callback = _callback

  # Exceptions bubbling out take precedence.
  try:
    with api.step.nest('exception status'):
      api.step('I am fine', ['echo', 'the chillest'])
      raise Exception('Whoa! Bang!')
  except Exception:
    pass

  try:
    with api.step.nest('failure status'):
      api.step('I fail', ['echo', 'fail'])
  except api.step.StepFailure:
    pass

  try:
    with api.step.nest('timeout status'):
      api.step('I fail', ['echo', 'fail'], timeout=1)
  except api.step.StepFailure as ex:
    assert ex.had_timeout

  # Change outer status after nesting is complete.
  with api.step.nest('versatile status') as nest_step:
    with api.step.nest('inner step'):
      with api.step.nest('even deeper'):
        pass
  nest_step.presentation.status = api.step.FAILURE

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

  # OK to have a nest parent without any children
  with api.step.nest('lonely parent'):
    pass


def GenTests(api):
  yield (
    api.test('basic')
    + api.post_process(StepException, 'inherit status')
    + api.post_process(StepSuccess, 'last status')
    + api.post_process(StepFailure, 'callback status')

    + api.post_process(StepException, 'exception status')

    # TODO(iannucci): switch to build.proto so these can actually be
    # differentiated: annotator protocol only has a subset of the possible
    # statuses.
    + api.step_data('failure status.I fail', retcode=1)
    + api.post_process(StepFailure, 'failure status')

    # TODO(iannucci): switch to build.proto so these can actually be
    # differentiated: annotator protocol only has a subset of the possible
    # statuses.
    + api.step_data('timeout status.I fail', times_out_after=20)
    + api.post_process(StepFailure, 'timeout status')

    + api.post_process(StepFailure, 'versatile status')
  )
