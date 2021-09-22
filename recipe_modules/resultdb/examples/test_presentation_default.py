# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = "PY2+3"

DEPS = [
    'resultdb',
]

def RunSteps(api):
  api.resultdb.config_test_presentation()

def GenTests(api):
  yield api.test('basic')
