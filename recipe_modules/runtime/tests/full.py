# Copyright 2017 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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


def GenTests(api):
  yield api.test('basic') + api.runtime(is_experimental=False)
