# Copyright 2021 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from PB.tricium.data import Data
from PB.recipe_modules.recipe_engine.tricium.tests.enforce_comments_num_limit import InputProps

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    assertions,
    buildbucket,
    properties,
    proto,
    tricium,
)


@dataclass
class DEPS(RecipeScriptApi):
  assertions: assertions.API
  buildbucket: buildbucket.API
  properties: properties.API
  proto: proto.API
  tricium: tricium.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  buildbucket: buildbucket.TEST_API
  properties: properties.TEST_API

PROPERTIES = InputProps


def RunSteps(api: DEPS, props):
  api.tricium._comments_num_limit = 5  # Reset the limit to 5 for testing.
  for i in range(10):
    api.tricium.add_comment('test', 'test message', 'path/to/file_%d' % i)

  step = api.tricium.write_comments()
  result = step.presentation.properties.get('tricium')
  expected = api.proto.encode(
      props.expected_results,
      'JSONPB',
      indent=0,
      preserving_proto_field_name=False)
  api.assertions.assertEqual(result, expected)


def GenTests(api: TEST_DEPS):
  yield (api.test('basic', api.buildbucket.try_build(project='chrome')) +
         api.properties(
             InputProps(
                 expected_results=Data.Results(comments=[
                     Data.Comment(
                         category='test',
                         message='test message',
                         path='path/to/file_%d' % i) for i in range(5)
                 ]))) + api.post_process(post_process.DropExpectation))
