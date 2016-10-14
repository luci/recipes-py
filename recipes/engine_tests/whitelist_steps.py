# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

DEPS = [
  'step',
]

def RunSteps(api):
  api.step('something unimportant', ['echo', 'sup doc'])
  api.step('something important', ['echo', 'crazy!'], env={'FLEEM': 'VERY YES'})
  api.step('another important', ['echo', 'INSANITY'])

def GenTests(api):
  yield api.test('all_steps')

  yield (api.test('single_step')
    + api.whitelist('something important')
  )

  yield (api.test('two_steps')
    + api.whitelist('something important')
    + api.whitelist('another important')
  )

  yield (api.test('selection')
    + api.whitelist('something important', 'env')
    + api.whitelist('another important', 'cmd')
  )

  yield (api.test('result')
    + api.whitelist('$result')
  )
