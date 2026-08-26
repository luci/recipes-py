# -*- coding: utf-8 -*-
# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    raw_io,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  raw_io: raw_io.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass


def RunSteps(api: DEPS):
  with api.assertions.assertRaises(TypeError) as caught:
    api.step(
        'step requiring text data', ['cat', 'foo'],
        stdout=api.raw_io.output_text('out'),
        step_test_data=lambda: api.raw_io.test_api.stream_output(b'blah\n'))
  api.assertions.assertTrue(
      str(caught.exception).startswith('test data must be text data'))

  with api.assertions.assertRaises(TypeError) as caught:
    api.step(
        'step requiring binary data', ['cat', 'foo'],
        stdout=api.raw_io.output('out'),
        step_test_data=lambda: api.raw_io.test_api.stream_output_text('blah\n'))
  api.assertions.assertTrue(
      str(caught.exception).startswith('test data must be binary data'))


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
