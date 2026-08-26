# Copyright 2017 The LUCI Authors
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

from dataclasses import dataclass
from recipe_engine.recipe_api import RecipeScriptApi
from recipe_engine.recipe_test_api import RecipeTestApi
from RECIPE_MODULES.recipe_engine import (
    properties,
    step,
    url,
)


@dataclass
class DEPS(RecipeScriptApi):
  properties: properties.API
  step: step.API
  url: url.API


@dataclass
class TEST_DEPS(RecipeTestApi):
  properties: properties.TEST_API


def RunSteps(api: DEPS):
  api.url.validate_url(api.properties['url_to_validate'])


def GenTests(api: TEST_DEPS):
  yield (api.test('basic') +
      api.properties(url_to_validate='https://example.com'))

  yield (api.test('no_scheme') +
      api.properties(url_to_validate='example.com') +
      api.expect_exception('ValueError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdownRE,
          r"URL scheme must be either http:// or https://",
      ) +
      api.post_process(post_process.DropExpectation))

  yield (api.test('invalid_scheme') +
      api.properties(url_to_validate='ftp://example.com') +
      api.expect_exception('ValueError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdownRE,
          r"URL scheme must be either http:// or https://",
      ) +
      api.post_process(post_process.DropExpectation))

  yield (api.test('no_host') +
      api.properties(url_to_validate='https://') +
      api.expect_exception('ValueError') +
      api.post_process(post_process.StatusException) +
      api.post_process(
          post_process.SummaryMarkdownRE,
          r"URL must specify a network location.",
      ) +
      api.post_process(post_process.DropExpectation))
