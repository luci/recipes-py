# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from __future__ import annotations

DEPS = [
    'resultdb',
]

def RunSteps(api):
  api.resultdb.config_test_presentation(
    ['v.gpu'],
    ['status', 'v.test_suite', 'name'],
  )

def GenTests(api):
  yield api.test('basic')
