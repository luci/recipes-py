# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

DEPS = [
    'buildbucket',
    'cv',
    'step',
]

from PB.go.chromium.org.luci.buildbucket.proto.build import Build


def RunSteps(api):
  assert not api.cv.do_not_retry_build
  api.cv.set_do_not_retry_build()
  assert api.cv.do_not_retry_build
  api.cv.set_do_not_retry_build()  # noop.


def GenTests(api):
  yield api.test('example')
