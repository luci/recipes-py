# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'futures',
  'step',
]


def RunSteps(api):
  # This normal step checks against regressions in the greenlet spawning
  # function. Previously the engine would accidentally add the spawned greenlet
  # to this normal step, resulting in deadlock at `fut.result()` below.
  api.step('normal step', ['echo', 'I am pretty normal'])

  fut = api.futures.spawn(api.step, 'do work', cmd=['something'])
  if fut.exception():
    assert isinstance(fut.exception(), api.step.StepFailure), (
      'Some other exception?')
  fut.result()

  assert fut.done, 'What? The future must be done after getting its result.'

  api.step('run if success', cmd=None)

def GenTests(api):
  yield (
    api.test('success')
    + api.post_check(lambda check, steps: check(
        'run if success' in steps
    ))
  )

  yield (
    api.test('failure')
    + api.step_data('do work', retcode=1)
    + api.post_check(lambda check, steps: check(
        steps['do work'].status == 'FAILURE'
    ))
    + api.post_check(lambda check, steps: check(
        'run if success' not in steps
    ))
  )
