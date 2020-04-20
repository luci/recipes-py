# Copyright 2020 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'path',
  'proto',
  'step',
]

from PB.recipe_modules.recipe_engine.proto.tests.placeholders import SomeMessage


def RunSteps(api):
  step = api.step('read from script', [
    'python', api.resource('dump.py'), api.proto.output(SomeMessage, 'JSONPB'),
  ])
  assert step.proto.output == SomeMessage(field="hello")

  step = api.step('read missing output', [
    'python', api.resource('dump.py'),
    api.proto.output(SomeMessage, 'JSONPB',
                     leak_to=api.path['start_dir'].join('gone')),
  ])

  step = api.step('read invalid output', [
    'python', api.resource('dump.py'),
    api.proto.output(SomeMessage, 'JSONPB',
                     leak_to=api.path['start_dir'].join('gone')),
  ])

  api.step('write to script', [
    'python', api.resource('read.py'),
    api.proto.input(SomeMessage(field="sup"), 'JSONPB'),
  ])


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('read from script', api.proto.output(
          SomeMessage(field="hello"))),
      api.step_data('read missing output', api.proto.backing_file_missing()),
      api.step_data('read invalid output', api.proto.invalid_contents()),
  )
