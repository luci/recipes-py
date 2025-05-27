# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that step_data can accept multiple specs at once."""


from __future__ import annotations

from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from recipe_engine.post_process import Filter, DoesNotRun, MustRun

DEPS = [
  'context',
  'step',
  'properties',
]

PROPERTIES = {
  'fakeit': Property(kind=bool, default=True),
}

def RunSteps(api, fakeit):
  api.step('something unimportant', ['echo', 'sup doc'])
  with api.context(env={'FLEEM': 'VERY YES'}):
    api.step('something important', ['echo', 'crazy!'])
  api.step('another important', ['echo', 'INSANITY'])
  if fakeit:
    api.step('fakestep', ['echo', 'FAAAAKE'])
  step_result = api.step('set build properties', ['dummy'])
  step_result.presentation.properties['test_build_property'] = True


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

  def assert_stuff(check, results):
    check('something important' in results)
    if check('another important' in results):
      check('INSANITY' in results['another important'].cmd)
    # drop the whole expectations, we're done here
    return {}

  yield api.test('custom_func') + api.post_process(assert_stuff)

  yield (
      api.test('set_build_properties') +
      api.post_process(post_process.PropertyEquals,
                       'test_build_property', True) +
      api.post_process(post_process.PropertiesDoNotContain,
                       'build_property_not_present') +
      api.post_process(post_process.DropExpectation)
  )
