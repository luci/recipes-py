# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
  'platform',
  'step',
]

def RunSteps(api):
  step_result = api.step('platform things', cmd=None)
  step_result.presentation.logs['name'] = [api.platform.name]
  step_result.presentation.logs['bits'] = [str(api.platform.bits)]
  step_result.presentation.logs['arch'] = [api.platform.arch]


def GenTests(api):
  yield api.test('linux64') + api.platform('linux', 64)
  yield api.test('mac64') + api.platform('mac', 64)
  yield api.test('win32') + api.platform('win', 32)
