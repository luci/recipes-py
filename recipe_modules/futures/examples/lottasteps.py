# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This tests the engine's ability to handle many simultaneously-started steps.

Prior to this, logdog butler and the recipe engine would run out of file
handles, because every spawn_immediate would immediately generate all log
handles for the step, instead of waiting for the step's cost to be available.
"""

from recipe_engine.post_process import DropExpectation

from PB.recipe_modules.recipe_engine.futures.examples.lottasteps import Input
from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import common

DEPS = [
  'futures',
  'properties',
  'step',
]

PROPERTIES = Input


def RunSteps(api, props):
  work = []
  for i in range(props.num_steps):
    work.append(api.futures.spawn_immediate(
        api.step, ('hw %d' % i), ['sleep', '.1'],
        __name='step %d' % i,
    ))
  api.futures.wait(work)
  return RawResult(
      summary_markdown="Ran %d steps" % (len(work),),
      status=common.SUCCESS,
  )


def GenTests(api):
  yield (
    api.test('basic')
    + api.properties(num_steps=10)
    + api.post_process(DropExpectation)
  )
