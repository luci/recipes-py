# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""

from recipe_engine.recipe_api import Property
from recipe_engine.post_process import Filter, DoesNotRun, MustRun

DEPS = [
  'step',
  'properties',
]

PROPERTIES = {
  'fakeit': Property(kind=bool, default=True),
}

def RunSteps(api, fakeit):
  api.step('something unimportant', ['echo', 'sup doc'])
  api.step('something important', ['echo', 'crazy!'], env={'FLEEM': 'VERY YES'})
  api.step('another important', ['echo', 'INSANITY'])
  if fakeit:
    api.step('fakestep', ['echo', 'FAAAAKE'])


def GenTests(api):
  yield api.test('all_steps') + api.post_process(MustRun, 'fakestep')

  yield (api.test('single_step')
    + api.post_process(Filter('something important'))
  )

  yield (api.test('two_steps')
    + api.post_process(Filter('something important', 'another important'))
  )

  f = Filter()
  f = f.include_re(r'.*\bimportant', ['cmd', 'env'], at_least=2, at_most=2)
  yield (api.test('selection')
    + api.properties(fakeit=False)
    + api.post_process(DoesNotRun, 'fakestep')
    + api.post_process(f)
  )

  yield api.test('result') + api.post_process(Filter('$result'))
