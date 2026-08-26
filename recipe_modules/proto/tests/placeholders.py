# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    path,
    proto,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  path: path.API
  proto: proto.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  proto: proto.TEST_API

from PB.recipe_modules.recipe_engine.proto.tests.placeholders import SomeMessage


def RunSteps(api: DEPS):
  step = api.step('read from script', [
    'python3', api.resource('dump.py'), api.proto.output(SomeMessage, 'JSONPB'),
  ])
  assert step.proto.output == SomeMessage(field="hello")

  step = api.step('read from script stdout (jsonpb)', [
    'python3', api.resource('dump.py'),
  ], stdout=api.proto.output(SomeMessage, 'JSONPB'),)
  assert step.stdout == SomeMessage(field="cool stuff")

  step = api.step('read from script stdout (binary)', [
    'python3', api.resource('dump.py'),
  ], stdout=api.proto.output(SomeMessage, 'BINARY'),)
  assert step.stdout == SomeMessage(field="cool stuff")

  step = api.step('read missing output', [
    'python3', api.resource('dump.py'),
    api.proto.output(SomeMessage, 'JSONPB',
                     leak_to=api.path.start_dir / 'gone'),
  ])

  step = api.step('read invalid output', [
    'python3', api.resource('dump.py'),
    api.proto.output(SomeMessage, 'JSONPB',
                     leak_to=api.path.start_dir / 'gone'),
  ])

  api.step('write to script (jsonpb)', [
    'python3', api.resource('read.py'),
    api.proto.input(SomeMessage(field="sup"), 'JSONPB'),
  ])

  api.step('write to script (binary)', [
    'python3', api.resource('read.py'),
    api.proto.input(SomeMessage(field="sup"), 'BINARY'),
  ])


def GenTests(api: TEST_DEPS):
  yield api.test(
      'basic',
      api.step_data('read from script', api.proto.output(
          SomeMessage(field="hello"))),
      api.step_data('read from script stdout (jsonpb)', api.proto.output_stream(
          SomeMessage(field="cool stuff"))),
    api.step_data('read from script stdout (binary)', api.proto.output_stream(
      SomeMessage(field="cool stuff"))),
      api.step_data('read missing output', api.proto.backing_file_missing()),
      api.step_data('read invalid output', api.proto.invalid_contents()),
  )
