# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
  'futures',
  'step',
]


def RunSteps(api):
  futures = []
  for i in range(10):
    def _runner(i):
      api.step(
          'sleep loop [%d]' % (i+1),
          ['python3', '-u', api.resource('sleep_loop.py'), i],
      )
      return i + 1
    futures.append(api.futures.spawn(_runner, i))

  with api.futures.iwait(futures) as iter:
    for helper in iter:
      result = helper.result()
      if result < 5:
        api.step('Sleeper %d complete' % helper.result(), cmd=None)
      else:
        result = api.step('OH NO QUIT QUIT QUIT', cmd=None)
        result.presentation.status = 'FAILURE'
        raise api.step.StepFailure('boomzors')


def GenTests(api):
  yield api.test('basic', status='FAILURE')
