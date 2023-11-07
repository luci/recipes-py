# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
  'step',
  'properties',
  'cipd',
]

PROPERTIES = {
  'from_recipe': Property(kind=bool, default=False),
  'attribute': Property(kind=bool, default=False),
  'module': Property(kind=bool, default=False),
}

def RunSteps(api, from_recipe, attribute, module):
  if from_recipe:
    api.missing_module('baz')
  if attribute:
    api.cipd.missing_method('baz')
  if module:
    api.cipd.m.missing_module('baz')

def GenTests(api):
  yield (
      api.test('from_recipe') +
      api.properties(from_recipe=True) +
      api.expect_exception('ModuleInjectionError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: ModuleInjectionError('Recipe has no "
          "dependency 'missing_module'. (Add it to DEPS?)')",
      ) +
      api.post_process(post_process.DropExpectation))

  yield (
      api.test('attribute') +
      api.properties(attribute=True) +
      api.expect_exception('AttributeError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: AttributeError(''CIPDApi' object has no "
          "attribute 'missing_method'')",
      ) +
      api.post_process(post_process.DropExpectation))

  yield (
      api.test('module') +
      api.properties(module=True) +
      api.expect_exception('ModuleInjectionError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: ModuleInjectionError('Recipe Module "
          "'cipd' has no dependency 'missing_module'. (Add it to "
          "__init__.py:DEPS?)')",
      ) +
      api.post_process(post_process.DropExpectation))
