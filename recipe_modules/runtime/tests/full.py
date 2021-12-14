# Copyright 2017 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

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

  assert api.runtime.in_global_shutdown, "Not in global_shutdown after compile"

  api.step.empty('should_skip') # Should be skipped


def GenTests(api):
  yield api.test(
      'basic',
      api.runtime(is_experimental=False),
      api.runtime.global_shutdown_on_step('compile'),
  )

  yield api.test(
      'shutdown-before',
      api.runtime(is_experimental=False),
      api.runtime.global_shutdown_on_step('compile', 'before'),
  )
