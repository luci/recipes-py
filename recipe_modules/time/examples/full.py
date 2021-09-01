# Copyright 2014 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

import datetime

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
  'step',
  'time',
]


def RunSteps(api):
  now = api.time.time()
  api.time.sleep(5)
  api.step('echo', ['echo', str(now)])
  assert isinstance(api.time.utcnow(), datetime.datetime)
  assert isinstance(api.time.ms_since_epoch(), int)


def GenTests(api):
  yield api.test('defaults')
  yield api.test('seed_and_step') + api.time.seed(123) + api.time.step(2)
