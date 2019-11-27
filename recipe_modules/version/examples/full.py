# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.


DEPS = [
  'version',
]


def RunSteps(api):
  assert api.version.parse('1.0.0') > api.version.parse('0.9')


def GenTests(api):
  yield api.test('basic') + api.post_process(lambda *a: {})
