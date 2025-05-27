# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import contextlib
from typing import Generator

from PB.recipe_modules.recipe_engine.defer.tests import (properties as
                                                         properties_pb2)
from recipe_engine import post_process, recipe_test_api, step_data

DEPS = [
    'context',
    'defer',
    'properties',
    'step',
]

PROPERTIES = properties_pb2.NonDeferredInputProps


class CollectTestError(Exception):
  pass


def RunSteps(api, props):

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
