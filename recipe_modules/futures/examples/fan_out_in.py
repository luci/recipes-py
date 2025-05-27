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
  for _ in range(10):
    futures.append(api.futures.spawn(
        api.step('sleep loop', [
          'python3', '-u', api.resource('sleep_loop.py'),
        ], cost=api.step.ResourceCost(cpu=2*api.step.CPU_CORE))
    ))

  assert len(api.futures.wait(futures)) == 10, "All done"


def GenTests(api):
  yield (
    api.test('basic')
    + api.post_check(lambda check, steps: check(
        steps['sleep loop'].cost.cpu == 2000
    ))
  )
