# Copyright 2023 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import contextlib
from typing import Generator

from PB.recipe_modules.recipe_engine.defer.tests import (properties as
                                                         properties_pb2)
from recipe_engine import post_process, recipe_test_api, step_data

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    context,
    defer,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  context: context.API
  defer: defer.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API

PROPERTIES = properties_pb2.NonDeferredInputProps


class CollectTestError(Exception):
  pass


def RunSteps(api: DEPS, props):

  def keyerror():
    raise KeyError()

  def valueerror():
    raise ValueError()

  with api.defer.context(collect_step_name='collect') as defer:
    if props.fail:
      defer(keyerror)
      defer(valueerror)
    raise OSError


def GenTests(api) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'pass',
      api.properties(properties_pb2.NonDeferredInputProps(fail=False)),
      api.expect_exception('OSError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'fail',
      api.properties(properties_pb2.NonDeferredInputProps(fail=True)),
      api.expect_exception('KeyError'),
      api.expect_exception('OSError'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
