# Copyright 2019 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""This tests the engine's ability to handle many simultaneously-started steps.

Prior to this, logdog butler and the recipe engine would run out of file
handles, because every spawn_immediate would immediately generate all log
handles for the step, instead of waiting for the step's cost to be available.
"""

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

from PB.recipe_modules.recipe_engine.futures.examples.lottasteps import Input
from PB.recipe_engine.result import RawResult
from PB.go.chromium.org.luci.buildbucket.proto import common

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    futures,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  futures: futures.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API

PROPERTIES = Input


def RunSteps(api: DEPS, props):
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


def GenTests(api: TEST_DEPS):
  yield (
    api.test('basic')
    + api.properties(num_steps=10)
    + api.post_process(DropExpectation)
  )
