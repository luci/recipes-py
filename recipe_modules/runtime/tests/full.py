# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import json

from recipe_engine import post_process, recipe_api, recipe_test_api

DEPS = [
  'runtime',
  'step',
]


def RunSteps(api: recipe_api.RecipeScriptApi):
  api.step('show properties', [])
  api.step.active_result.presentation.logs['result'] = [
    'is_experimental: %r' % (api.runtime.is_experimental,),
  ]

  assert not api.runtime.in_global_shutdown, "Entered global_shutdown early"

  api.step.empty('compile')

  assert api.runtime.in_global_shutdown, "Not in global_shutdown after compile"

  api.step.empty('should_skip')  # Should be skipped


def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Iterator[recipe_test_api.TestData]:
  yield api.test(
      'basic',
      api.runtime(is_experimental=False),
      api.runtime.global_shutdown_on_step('compile'),
      api.post_process(post_process.StepSuccess, 'compile'),
      api.post_process(post_process.StepException, 'should_skip'),
      status='CANCELED',
  )

  yield api.test(
      'shutdown-before',
      api.runtime(is_experimental=False),
      api.runtime.global_shutdown_on_step('compile', 'before'),
      api.post_process(post_process.StepException, 'compile'),
      api.post_process(post_process.DoesNotRun, 'should_skip'),
      status='CANCELED',
  )
