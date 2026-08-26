# Copyright 2020 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    path,
    proto,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  path: path.API
  proto: proto.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  pass

from PB.recipe_modules.recipe_engine.proto.tests.placeholders import SomeMessage


def RunSteps(api: DEPS):
  text = api.proto.encode(SomeMessage(field='text'), 'TEXTPB')
  api.assertions.assertEqual(text, 'field: "text"\n')
  api.assertions.assertEqual(
    api.proto.decode(text, SomeMessage, 'TEXTPB'),
    SomeMessage(field="text")
  )

  json = api.proto.encode(SomeMessage(field='json'), 'JSONPB')
  api.assertions.assertEqual(json, '{\n  "field": "json"\n}')
  api.assertions.assertEqual(
    api.proto.decode(json, SomeMessage, 'JSONPB'),
    SomeMessage(field="json")
  )

  binary = api.proto.encode(SomeMessage(field='binary'), 'BINARY')
  api.assertions.assertEqual(binary, b'\n\x06binary')
  api.assertions.assertEqual(
    api.proto.decode(binary, SomeMessage, 'BINARY'),
    SomeMessage(field="binary")
  )


def GenTests(api: TEST_DEPS):
  yield api.test('basic')
