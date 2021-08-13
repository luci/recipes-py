# Copyright 2015 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
  'platform',
  'step',
  'version',
]

def RunSteps(api):
  step_result = api.step('platform things', cmd=None)
  step_result.presentation.logs['name'] = [api.platform.name]
  step_result.presentation.logs['bits'] = [str(api.platform.bits)]
  step_result.presentation.logs['arch'] = [api.platform.arch]
  step_result.presentation.logs['cpu_count'] = [str(api.platform.cpu_count)]
  step_result.presentation.logs['memory'] = [str(api.platform.total_memory)]
  step_result.presentation.logs['mac_release'] = [
      repr(api.platform.mac_release)]
  step_result.presentation.logs['new_mac'] = [str(
      api.platform.mac_release is not None and
      api.platform.mac_release >= api.version.parse('10.14.0')
  )]


def GenTests(api):
  yield api.test('linux64') + api.platform('linux', 64)
  yield api.test('mac64') + api.platform('mac', 64)
  yield api.test('mac64-new') + api.platform('mac', 64, mac_release='10.14.0')
  yield api.test('win32') + api.platform('win', 32)
  yield api.test('arm64') + api.platform('linux', 64, 'arm')
