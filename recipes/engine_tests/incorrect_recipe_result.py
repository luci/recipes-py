# Copyright 2015 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that engine.py can handle unknown recipe results."""

from __future__ import annotations

from PB.recipe_engine import result as result_pb2
from PB.recipes.recipe_engine.engine_tests.incorrect_recipe_result import InputProps

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    json,
    properties,
    step,
)


@dataclass
class DEPS(RecipeScriptApi):
  json: json.API
  properties: properties.API
  step: step.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API

PROPERTIES = InputProps


def RunSteps(api: DEPS, props):
  if props.use_result_type:
    return result_pb2.Result()

  return {'summary': 'test'}


def GenTests(api: TEST_DEPS):
  yield api.test(
      'incorrect_object_returned',
      api.properties(InputProps(use_result_type=False)),
      api.post_process(
          post_process.SummaryMarkdownRE,
          ('"<(class|type) \'dict\'>" is not a valid return type for recipes\.'
           ' Did you mean to use "RawResult"\?')),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'result_object_returned',
      api.properties(InputProps(use_result_type=True)),
      api.post_process(post_process.SummaryMarkdown,
                       ('"<class \'recipe_engine.result_pb2.Result\'>"'
                        ' is not a valid return type for recipes.'
                        ' Did you mean to use "RawResult"?')),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
