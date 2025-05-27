# Copyright 2024 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

from recipe_engine import post_process

DEPS = [
  'recipe_engine/buildbucket',
  'recipe_engine/change_verifier',
  'recipe_engine/step',
]


def RunSteps(api):
  group = api.change_verifier.match_config(
      'chromium-review.googlesource.com',
      123456)

  if group:
    api.step.empty('group found')
    api.step.empty(group)

  else:
    api.step.empty('group not found')


def GenTests(api):
  yield api.test(
      'pass',
      api.buildbucket.ci_build(),
      api.post_process(post_process.MustRun, 'group found'),
      api.post_process(post_process.MustRun, 'chromium-src'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'not-found',
      api.buildbucket.ci_build(),
      api.step_data('match-config', retcode=1),
      api.post_process(post_process.MustRun, 'group not found'),
      api.post_process(post_process.DropExpectation),
  )
