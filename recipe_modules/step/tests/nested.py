# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime

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

  # Outer nested step's status gets the worst child's status by default.
  with api.step.nest('inherit status'):
    with api.step.nest('inner step') as inner_step_presentation:
      inner_step_presentation.step_text += 'Hey!'
      inner_step_presentation.status = api.step.EXCEPTION

  # But, you could also pick the last status.
  with api.step.nest('last status', status='last'):
    with api.step.nest('failpants') as failpants_presentation:
      failpants_presentation.status = api.step.EXCEPTION
    api.step('everything OK', ['echo', 'hi'])

  # DEPRECATED; DO NOT USE
  with api.step.nest('extra_nonsense') as fake_step_data:
    fake_step_data.presentation.step_text = (
      'Just use the yielded object as StepPresentation directly, do not'
      'use the `.presentation` accessor.'
    )

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
      api.step(
          'I fail', ['echo', 'fail'], timeout=datetime.timedelta(seconds=1))
  except api.step.StepFailure as ex:
    assert ex.had_timeout

  # Duplicate nesting names with unique child steps
  for i in range(3):
    with api.step.nest('Do Iteration'):
      api.step('Iterate %d' % i, ['echo', 'lerpy'])

  api.step('simple thing', ['sleep', '1'])

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

    + api.post_check(lambda check, steps: check(
        'StepPresentation' in steps['extra_nonsense'].step_text
    ))

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
  )
