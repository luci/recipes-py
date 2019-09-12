# -*- coding: utf-8 -*-

# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


"""A fast-running recipe which comprehensively covers all StepPresentation
features available in the recipe engine."""

DEPS = [
  'python',
  'raw_io',
  'step',
]

def named_step(api, name):
  return api.python(name, api.resource('dual_output.py'))

def RunSteps(api):
  with api.step.nest('names'):
    named_step(api, 'Some Name')
    named_step(api, 'Unicode Name 💩')

    named_step(api, 'Duplicate')
    named_step(api, 'Duplicate')

  with api.step.nest('non duplicate'):
    named_step(api, 'Duplicate')

  with api.step.nest('nesting'):
    named_step(api, 'pre-deep')
    with api.step.nest('deeper'):
      named_step(api, 'deep')

      with api.step.nest('💩-ier'):
        named_step(api, '💩')

      named_step(api, 'post 💩')

    named_step(api, 'post deep')

  with api.step.nest('presentation'):
    with api.step.nest('text'):
      result = named_step(api, 'step_text')
      result.presentation.step_text = 'HI THERE I AM STEP TEXT, 💩'

      result = named_step(api, 'step_summary')
      result.presentation.step_summary = 'HI THERE I AM STEP SUMMARY, 💩'

      result = named_step(api, 'all text')
      result.presentation.step_text = 'HI THERE I AM STEP TEXT, 💩'
      result.presentation.step_summary = 'HI THERE I AM STEP SUMMARY, 💩'

    with api.step.nest('links'):
      result = named_step(api, 'links')
      result.presentation.links['cool link'] = 'https://cool.link.example.com'
      result.presentation.links['💩 link'] = 'https://💩.link.example.com'

    with api.step.nest('logs'):
      result = named_step(api, 'logs')
      result.presentation.logs['cool log'] = [
        'cool %d' % i for i in range(10)
      ]
      result.presentation.logs['💩 log'] = [
        '💩 %d' % i for i in range(10)
      ]

  # Re-use stdout after redirect
  # TODO(iannucci): this is a bit dirty; once we drop @@@ see if we can do this
  # more cleanly.
  result = api.step('capture stdout', ['echo', 'OHAI'],
                    stdout=api.raw_io.output_text())
  result.presentation.logs['stdout'] = result.stdout.splitlines()

  with api.step.nest('properties'):
    result = named_step(api, 'logs')
    result.presentation.properties['str_prop'] = 'hi'
    result.presentation.properties['obj_prop'] = {'hi': 'there'}
    result.presentation.properties['💩_prop'] = ['💩'] * 10



def GenTests(api):
  yield (
    api.test('basic')
    + api.step_data('capture stdout', stdout=api.raw_io.output_text('OHAI'))
  )
