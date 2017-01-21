# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'platform',
  'step',
]

def RunSteps(api):
  step_result = api.step('platform things', cmd=None)
  step_result.presentation.logs['name'] = [api.platform.name]
  step_result.presentation.logs['bits'] = [str(api.platform.bits)]
  step_result.presentation.logs['arch'] = [api.platform.arch]
  step_result.presentation.logs['cpu_count'] = [str(api.platform.cpu_count)]


def GenTests(api):
  yield api.test('linux64') + api.platform('linux', 64)
  yield api.test('mac64') + api.platform('mac', 64)
  yield api.test('win32') + api.platform('win', 32)
  yield api.test('four_cores') + api.platform.cpu_count(4)
