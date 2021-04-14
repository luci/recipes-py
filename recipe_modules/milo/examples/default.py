# Copyright 2021 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'milo',
]

def RunSteps(api):
  api.milo.config_test_presentation()

def GenTests(api):
  yield api.test('basic')
