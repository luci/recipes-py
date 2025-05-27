# Copyright 2025 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

"""Tests that we can pass data via api.recipe_test_data."""

from __future__ import annotations

from recipe_engine.post_process import DropExpectation

DEPS = [
  'step',
]


def RunSteps(api):
  target = 'production'
  if api._test_data.enabled:
    if 'target' in api._test_data:
      target = api._test_data['target']
  api.step('echo', ['echo', target])


def GenTests(api):
  yield api.test(
      'default',
      api.post_check(
          lambda check, steps: check([..., 'production'] in steps['echo'].cmd)
      ),
      api.post_process(DropExpectation),
  )
  yield api.test(
      'override',
      api.recipe_test_data(target='override'),
      api.post_check(
          lambda check, steps: check([..., 'override'] in steps['echo'].cmd)
      ),
      api.post_process(DropExpectation),
  )
