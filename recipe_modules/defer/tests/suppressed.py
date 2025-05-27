# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import contextlib
from typing import Generator

from PB.recipe_modules.recipe_engine.defer.tests import (
    properties as properties_pb2
)
from recipe_engine import post_process, recipe_api, recipe_test_api

DEPS = [
    'defer',
    'properties',
    'step',
]

PROPERTIES = properties_pb2.SuppressedInputProps


class SuppressedFailure(Exception):
    pass


class NormalFailure(Exception):
    pass


def RunSteps(
    api: recipe_api.RecipeApi,
    props: properties_pb2.SuppressedInputProps,
):

  def fail() -> None:
    raise SuppressedFailure()

  def step() -> None:
    if props.fail:
      raise NormalFailure()

  with api.defer.context() as defer:
    defer(fail)
    defer.suppress()
    defer(step)
  api.step.empty('all steps succeeded')  # pragma: no cover


def GenTests(api) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'not-suppressed',
      api.properties(properties_pb2.SuppressedInputProps(fail=False)),
      api.post_process(post_process.DoesNotRun, 'all steps succeeded'),
      api.expect_exception('SuppressedFailure'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'suppressed',
      api.properties(properties_pb2.SuppressedInputProps(fail=True)),
      api.post_process(post_process.DoesNotRun, 'all steps succeeded'),
      api.expect_exception('NormalFailure'),
      api.post_process(post_process.DropExpectation),
  )
