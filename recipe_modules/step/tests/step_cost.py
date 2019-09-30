# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine.types import ResourceCost

DEPS = [
  'step',
]


def RunSteps(api):
  api.step('null step', [])
  api.step('zero step', ['echo', 'hi'], cost=None)

  api.step('default step', ['echo', 'hi'])
  api.step('max cpu step', ['echo', 'hi'],
           cost=api.step.ResourceCost(cpu=api.step.MAX_CPU))
  api.step('max memory step', ['echo', 'hi'],
           cost=api.step.ResourceCost(memory=api.step.MAX_MEMORY))
  api.step('over-max step', ['echo', 'hi'],
           cost=api.step.ResourceCost(
               cpu=api.step.MAX_CPU*2, memory=api.step.MAX_MEMORY*2))

def GenTests(api):
  yield (
    api.test('basic')
    + api.post_check(lambda check, steps: check(
        steps['null step'].cost == ResourceCost.zero()
    ))
    + api.post_check(lambda check, steps: check(
        steps['zero step'].cost == ResourceCost.zero()
    ))
    + api.post_check(lambda check, steps: check(
        steps['default step'].cost == ResourceCost()
    ))
    + api.post_check(lambda check, steps: check(
        steps['max cpu step'].cost == ResourceCost(cpu=8 * 1000)
    ))
    + api.post_check(lambda check, steps: check(
        steps['max memory step'].cost == ResourceCost(memory=16384)
    ))
    + api.post_check(lambda check, steps: check(
        steps['over-max step'].cost == ResourceCost(cpu=8 * 1000, memory=16384)
    ))
  )
