# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests error checking around multiple placeholders in a single step."""

from recipe_engine.post_process import DropExpectation

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'assertions',
  'json',
  'step',
]


def RunSteps(api):
  # illegal; multiple unnamed placeholders of the same kind "json.output".
  with api.assertions.assertRaisesRegexp(
      ValueError, r'conflicting .*: \[\'json\.output unnamed\'\]'):
    api.step('step 1', ['cmd', api.json.output(), api.json.output()])

  # illegal; multiple named placeholders with the same name
  with api.assertions.assertRaisesRegexp(
      ValueError, r'conflicting .*: \["json\.output named \'bob\'"\]'):
    api.step('step 2', [
      'cmd',
      api.json.output(name='bob'),
      api.json.output(name='bob'),
    ])

  # legal; multiple named placeholders with unique names
  result = api.step('step 3', [
    'cmd',
    api.json.output(name='bob'),
    api.json.output(name='charlie'),
  ])
  api.assertions.assertEqual(result.json.outputs['bob'], 1)
  api.assertions.assertEqual(result.json.outputs['charlie'], 2)

  # legal; multiple of the same input placeholders
  result = api.step('step 4', [
    'cmd',
    api.json.input('bob'),
    api.json.input('charlie'),
  ])


def GenTests(api):
  yield (
    api.test('basic')
    + api.step_data(
        'step 3',
        api.json.output(1, name='bob'),
        api.json.output(2, name='charlie'),
    )
    + api.post_process(DropExpectation)
  )
