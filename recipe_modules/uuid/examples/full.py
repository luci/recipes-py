# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
  'step',
  'uuid',
]


def RunSteps(api):
  uuid = api.uuid.random()
  api.step('echo', ['echo', str(uuid)])


def GenTests(api):
  yield api.test('basic')
