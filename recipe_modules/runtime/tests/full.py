# Copyright 2023 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

import json

DEPS = [
  'runtime',
  'step',
]


def RunSteps(api):
  api.step('show properties', [])
  api.step.active_result.presentation.logs['result'] = [
    'is_experimental: %r' % (api.runtime.is_experimental,),
  ]

  assert not api.runtime.in_global_shutdown, "Entered global_shutdown early"

  api.step.empty('compile')

  assert api.runtime.in_global_shutdown, (  # pragma: no cover
      "Not in global_shutdown after compile"
  )

  api.step.empty('should_skip')  # pragma: no cover


def GenTests(api):
  yield api.test(
      'basic',
      api.runtime(is_experimental=False),
      api.runtime.global_shutdown_on_step('compile'),
      status='CANCELED',
  )

  yield api.test(
      'shutdown-before',
      api.runtime(is_experimental=False),
      api.runtime.global_shutdown_on_step('compile', 'before'),
      status='CANCELED',
  )
