# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'assertions',
  'path',
  'proto',
  'step',
]

from PB.recipe_modules.recipe_engine.proto.tests.placeholders import SomeMessage


def RunSteps(api):
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
  api.assertions.assertEqual(binary, '\n\x06binary')
  api.assertions.assertEqual(
    api.proto.decode(binary, SomeMessage, 'BINARY'),
    SomeMessage(field="binary")
  )


def GenTests(api):
  yield api.test('basic')
