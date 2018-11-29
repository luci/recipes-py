# -*- coding: utf-8 -*-

# Copyright 2018 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


"""A fast-running recipe which comprehensively covers all StepPresentation
features available in the recipe engine."""

DEPS = [
  'step',
]

def RunSteps(api):
  with api.step.nest('names'):
    api.step('Some Name', [])
    api.step('Unicode Name 💩', [])

    api.step('Duplicate', [])
    api.step('Duplicate', [])

  with api.step.nest('non duplicate'):
    api.step('Duplicate', [])

  with api.step.nest('nesting'):
    api.step('pre-deep', [])
    with api.step.nest('deeper'):
      api.step('deep', [])

      with api.step.nest('💩-ier'):
        api.step('💩', [])

      api.step('post 💩', [])

    api.step('post deep', [])

  with api.step.nest('presentation'):
    with api.step.nest('text'):
      result = api.step('step_text', [])
      result.presentation.step_text = 'HI THERE I AM STEP TEXT, 💩'

      result = api.step('step_summary', [])
      result.presentation.step_summary = 'HI THERE I AM STEP SUMMARY, 💩'

      result = api.step('all text', [])
      result.presentation.step_text = 'HI THERE I AM STEP TEXT, 💩'
      result.presentation.step_summary = 'HI THERE I AM STEP SUMMARY, 💩'

    with api.step.nest('links'):
      result = api.step('links', [])
      result.presentation.links['cool link'] = 'https://cool.link.example.com'
      result.presentation.links['💩 link'] = 'https://💩.link.example.com'

    with api.step.nest('logs'):
      result = api.step('logs', [])
      result.presentation.logs['cool log'] = [
        'cool %d' % i for i in range(10)
      ]
      result.presentation.logs['💩 log'] = [
        '💩 %d' % i for i in range(10)
      ]

  with api.step.nest('properties'):
    result = api.step('logs', [])
    result.presentation.properties['str_prop'] = 'hi'
    result.presentation.properties['obj_prop'] = {'hi': 'there'}
    result.presentation.properties['💩_prop'] = ['💩'] * 10



def GenTests(api):
  yield api.test('basic')


