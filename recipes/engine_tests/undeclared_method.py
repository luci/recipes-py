# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from PB.recipes.recipe_engine.engine_tests import (
    undeclared_method as undeclared_method_pb,
)

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
  'step',
  'properties',
  'cipd',
]

INLINE_PROPERTIES_PROTO = """
message InputProperties {
  bool from_recipe = 1;
  bool attribute = 2;
  bool module = 3;
}
"""

PROPERTIES = undeclared_method_pb.InputProperties

def RunSteps(api, props: undeclared_method_pb.InputProperties):
  if props.from_recipe:
    api.missing_module('baz')
  if props.attribute:
    api.cipd.missing_method('baz')
  if props.module:
    api.cipd.m.missing_module('baz')

def GenTests(api):
  yield (
      api.test('from_recipe') +
      api.properties(from_recipe=True) +
      api.expect_exception('ModuleInjectionError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: ModuleInjectionError(\"Recipe has no "
          "dependency 'missing_module'. (Add it to DEPS?)\")",
      ) +
      api.post_process(post_process.DropExpectation))

  yield (
      api.test('attribute') +
      api.properties(attribute=True) +
      api.expect_exception('AttributeError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: AttributeError(\"'CIPDApi' object has no "
          "attribute 'missing_method'\")",
      ) +
      api.post_process(post_process.DropExpectation))

  yield (
      api.test('module') +
      api.properties(module=True) +
      api.expect_exception('ModuleInjectionError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdown,
          "Uncaught Exception: ModuleInjectionError(\"Recipe Module "
          "'cipd' has no dependency 'missing_module'. (Add it to "
          "__init__.py:DEPS?)\")",
      ) +
      api.post_process(post_process.DropExpectation))
