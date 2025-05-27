# Copyright 2017 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

DEPS = [
  'properties',
  'step',
  'url',
]


def RunSteps(api):
  api.url.validate_url(api.properties['url_to_validate'])


def GenTests(api):
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
